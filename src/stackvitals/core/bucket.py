"""Optional storage outside git: the same files the stackvitals-data branch holds, kept in an S3-compatible bucket (AWS S3,
Cloudflare R2, MinIO and others that support conditional writes). For very busy repos and big orgs, where many runs
writing one branch collide. Files are stored by their content hash, and one manifest maps paths to hashes; the manifest
is replaced only if nobody replaced it since this run read it (If-Match), so overlapping runs converge as with git.
Requests are signed with AWS Signature V4; no SDK is needed."""
import hashlib
import hmac
import json
import os
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

MANIFEST = "manifest.json"
EMPTY = hashlib.sha256(b"").hexdigest()


class BucketError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sign(method: str, url: str, headers: dict, payload_sha: str, key_id: str, secret: str, region: str,
         now: datetime, service: str = "s3") -> dict:
    """The headers of a request signed with AWS Signature Version 4 (path-style URL)."""
    u = urlparse(url)
    stamp, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    all_headers = {**{k.lower(): str(v).strip() for k, v in headers.items()}, "host": u.netloc,
                   "x-amz-date": stamp, "x-amz-content-sha256": payload_sha}
    names = sorted(all_headers)
    query = "&".join(f"{quote(k, safe='-_.~')}={quote(v, safe='-_.~')}" for k, v in
                     sorted(tuple(p.split("=", 1)) if "=" in p else (p, "") for p in u.query.split("&") if p))
    # The URL's path is already percent-encoded (BucketStore._url); S3 signs it as sent, never encoded twice.
    canonical = "\n".join([method, u.path or "/", query,
                           "".join(f"{n}:{all_headers[n]}\n" for n in names), ";".join(names), payload_sha])
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope, _sha(canonical.encode())])
    key = f"AWS4{secret}".encode()
    for part in (day, region, service, "aws4_request"):
        key = hmac.new(key, part.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    return {**{k: v for k, v in all_headers.items() if k != "host"},
            "authorization": f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, SignedHeaders={';'.join(names)}, Signature={signature}"}


class BucketStore:
    """The data branch's interface (open, dirty, commit_push, squash) over a bucket prefix."""

    def __init__(self, url: str, path: Path, endpoint: str, key_id: str, secret: str, region: str = "auto", client=None):
        u = urlparse(url)
        if u.scheme != "s3" or not u.netloc:
            raise BucketError("storage must look like s3://bucket/prefix")
        self.bucket, self.prefix = u.netloc, u.path.strip("/")
        self.endpoint = endpoint.rstrip("/")
        self.key_id, self.secret, self.region = key_id, secret, region or "auto"
        self.path = Path(path)
        self.client = client
        self.etag = None
        self.files: dict[str, str] = {}

    # -- requests ------------------------------------------------------------------------------------------------
    def _url(self, key: str) -> str:
        return f"{self.endpoint}/{self.bucket}/{quote(key, safe='/-_.~')}"

    def _key(self, name: str) -> str:
        return f"{self.prefix}/{name}" if self.prefix else name

    def _send(self, method: str, key: str, body: bytes = b"", headers: dict | None = None):
        if self.client is None:
            import httpx
            self.client = httpx.Client(timeout=60)
        url = self._url(key)
        signed = sign(method, url, headers or {}, _sha(body) if body else EMPTY, self.key_id, self.secret, self.region,
                      datetime.now(timezone.utc))
        for attempt in range(3):
            try:
                r = self.client.request(method, url, content=body or None, headers=signed)
            except Exception as exc:  # noqa: BLE001 - a dropped connection is retried, then said
                if attempt == 2:
                    raise BucketError(f"{method} {key}: {type(exc).__name__}") from exc
                time.sleep(1 + attempt)
                continue
            if r.status_code >= 500 and attempt < 2:
                time.sleep(1 + attempt)
                continue
            return r
        return r

    # -- the data branch's interface ------------------------------------------------------------------------------
    def open(self) -> None:
        """Download every file the manifest lists into `path`, remembering the manifest's ETag."""
        import shutil
        for attempt in range(3):
            if self.path.exists():
                shutil.rmtree(self.path)
            self.path.mkdir(parents=True)
            r = self._send("GET", self._key(MANIFEST))
            if r.status_code == 404:
                self.etag, self.files = None, {}
                return
            if r.status_code == 403:
                raise BucketError("reading the manifest: HTTP 403. The key must be able to read, write, delete and list "
                                  "the prefix; AWS answers a missing file with 403 when listing isn't allowed")
            if r.status_code != 200:
                raise BucketError(f"reading the manifest: HTTP {r.status_code}")
            self.etag = r.headers.get("etag")
            self.files = json.loads(r.content).get("files") or {}
            gone = False
            for name, digest in self.files.items():
                obj = self._send("GET", self._key(f"objects/{digest}"))
                if obj.status_code == 404:
                    gone = True  # another run swapped the manifest and cleaned up while this one read: start over
                    break
                if obj.status_code != 200 or _sha(obj.content) != digest:
                    raise BucketError(f"reading {name}: HTTP {obj.status_code}")
                target = self.path / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(obj.content)
            if not gone:
                return
            time.sleep(backoff(attempt))
        raise BucketError("the bucket kept changing while it was read; the next run will catch up")

    def _current(self) -> dict[str, tuple[str, bytes]]:
        out = {}
        for p in self.path.rglob("*"):
            if p.is_file():
                data = p.read_bytes()
                out[p.relative_to(self.path).as_posix()] = (_sha(data), data)
        return out

    def dirty(self) -> bool:
        return {k: v[0] for k, v in self._current().items()} != self.files

    def commit_push(self, message: str) -> str:
        """Upload new contents, then swap the manifest only if nobody swapped it since open(): "pushed", "unchanged",
        or "rejected" (the caller runs its steps again on the fresh data)."""
        now = self._current()
        files = {k: v[0] for k, v in now.items()}
        if files == self.files:
            return "unchanged"
        for name, (digest, data) in now.items():
            if self.files.get(name) != digest and digest not in set(self.files.values()):
                r = self._send("PUT", self._key(f"objects/{digest}"), data)
                if r.status_code not in (200, 201):
                    raise BucketError(f"writing {name}: HTTP {r.status_code}")
        doc = json.dumps({"files": files, "message": message, "at": datetime.now(timezone.utc).isoformat()},
                         sort_keys=True).encode()
        cond = {"if-match": self.etag} if self.etag else {"if-none-match": "*"}
        r = self._send("PUT", self._key(MANIFEST), doc, cond)
        if r.status_code in (409, 412):
            # Another run won. What this attempt uploaded stays: objects are named by content, so a run still working
            # may have uploaded the same file and be about to publish it. A few spare objects cost less than a lost one.
            return "rejected"
        if r.status_code not in (200, 201):
            raise BucketError(f"writing the manifest: HTTP {r.status_code}")
        old = set(self.files.values()) - set(files.values())
        self.etag, self.files = r.headers.get("etag"), files
        # Contents no file points to any more go; a run that read the old manifest only ever reads before this.
        for digest in old:
            self._send("DELETE", self._key(f"objects/{digest}"))
        return "pushed"

    def squash(self, message: str) -> str:
        return "unchanged"  # a bucket keeps no history to squash


def from_env(env: dict, path: Path, client=None) -> BucketStore | None:
    """The bucket store when STACKVITALS_STORAGE names one (s3://bucket/prefix), else None (the git branch)."""
    url = (env.get("STACKVITALS_STORAGE") or "").strip()
    if not url or url == "git":
        return None
    missing = [k for k in ("STACKVITALS_S3_ENDPOINT", "STACKVITALS_S3_KEY_ID", "STACKVITALS_S3_SECRET") if not env.get(k)]
    if missing:
        raise BucketError(f"storage {url} needs {', '.join(missing)}")
    return BucketStore(url, path, env["STACKVITALS_S3_ENDPOINT"], env["STACKVITALS_S3_KEY_ID"], env["STACKVITALS_S3_SECRET"],
                       env.get("STACKVITALS_S3_REGION") or "auto", client)


def backoff(attempt: int) -> float:
    # Two runs that collided shouldn't retry in step: a random wait that grows with each attempt.
    # Tests replay collisions on purpose (pytest names the running test in this variable) and skip the wait.
    if os.environ.get("STACKVITALS_NO_BACKOFF") == "1" or os.environ.get("PYTEST_CURRENT_TEST"):
        return 0
    return random.uniform(1, 4) * (attempt + 1)
