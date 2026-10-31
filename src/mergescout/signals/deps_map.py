"""Package -> source repo map from deps.dev (free, anonymous): the default version, release history, licence, advisories,
and how the repo link is known. A signed link is "verified"; a claimed one is checked against the repo's own manifest
(user decision D1), since anyone can point a package at a popular repo."""
import configparser
import http.client
import json
import re
import time
import tomllib
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import quote

from mergescout.github.graphql import GraphQLError, RateLimited
from mergescout.signals.bumps import _norm

API = "https://api.deps.dev"
SYSTEMS = {"npm": "NPM", "pypi": "PYPI"}
BATCH = 500
CLAIM_BATCH = 20
SAFE = re.compile(r"^[\w.-]+$")
SAFE_DIR = re.compile(r"^[\w.@+-]+(/[\w.@+-]+)*$")
SKIPPED = object()
# Pre-release markers in PyPI (1.0.0.dev6, 2.0rc1) and npm (6.0.0-beta.3) versions.
PRERELEASE = re.compile(r"(\d(a|b|rc|c)\d+|\.?dev\d*|\.?post\d*\.dev|-[0-9A-Za-z])", re.I)
# Dropped connections and resets come as several types; all of them are worth a retry.
NETWORK = (OSError, http.client.HTTPException)


def http_get_json(url: str, tries: int = 3) -> dict | None:
    # deps.dev states no rate limit; a short back-off covers its rare 5xx answers. 404 means "not known".
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "mergescout"}), timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            if attempt == tries - 1:
                raise
        except NETWORK:
            if attempt == tries - 1:
                raise
        time.sleep(2 ** attempt)
    return None


def http_post_json(url: str, body: dict, tries: int = 3) -> dict:
    data = json.dumps(body).encode()
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "mergescout"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read())
        except NETWORK:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)
    return {}


def lookup_packages(packages: list[tuple[str, str]], get_json=http_get_json, post_json=http_post_json,
                    now: datetime | None = None, workers: int = 8, budget_s: float | None = None) -> dict[tuple[str, str], dict]:
    """Per (ecosystem, name): default version, releases, repo and link kind, licences, advisories, deprecation.
    deps.dev slows down after many calls (23 s vs 333 s for the same 300 packages), so a time budget stops early."""
    wanted = list(dict.fromkeys((eco, name) for eco, name in packages if eco in SYSTEMS))
    deadline = time.time() + budget_s if budget_s else None

    def fetch(pair):
        # Past the budget nothing more is asked; those packages keep their previous answer.
        if deadline and time.time() > deadline:
            return SKIPPED
        try:
            return get_json(f"{API}/v3/systems/{SYSTEMS[pair[0]]}/packages/{quote(pair[1], safe='')}")
        except Exception:  # noqa: BLE001
            # One lost answer after retries only skips that package (it keeps its last answer).
            return SKIPPED
    with ThreadPoolExecutor(workers) as pool:
        found = list(pool.map(fetch, wanted))
    year_ago = ((now or datetime.now()) - timedelta(days=365)).strftime("%Y-%m-%d")
    out, keys = {}, []
    for (eco, name), pkg in zip(wanted, found):
        if pkg is SKIPPED:
            continue
        info = {"ecosystem": eco, "package": name, "version": None, "repo": None, "link": None, "licenses": [],
                "advisories": [], "deprecated": False, "deprecated_reason": None, "status": None, "releases_12m": 0,
                "last_release": None, "first_release": None}
        vs = [v for v in (pkg or {}).get("versions") or [] if v.get("publishedAt")]
        if vs:
            dates = sorted(v["publishedAt"][:10] for v in vs)
            default = next((v for v in vs if v.get("isDefault")), max(vs, key=lambda v: v["publishedAt"]))
            stable = [v for v in vs if not PRERELEASE.search(v["versionKey"]["version"])]
            # A pre-release default (httpx 1.0.0.dev6) often lacks the repo link; the newest stable release speaks for the package.
            if PRERELEASE.search(default["versionKey"]["version"]) and stable:
                default = max(stable, key=lambda v: v["publishedAt"])
            # Nightly and dev builds are not releases; a package with only pre-releases keeps them.
            counted = sorted(v["publishedAt"][:10] for v in stable) or dates
            info.update(version=default["versionKey"]["version"], first_release=dates[0], last_release=counted[-1],
                        releases_12m=sum(d >= year_ago for d in counted), release_rule=RELEASE_RULE)
            keys.append((eco, name, info["version"]))
        out[(eco, name)] = info
    by_key = {(SYSTEMS[e], n, v): (e, n) for e, n, v in keys}
    for i in range(0, len(keys), BATCH):
        body = {"requests": [{"versionKey": {"system": SYSTEMS[e], "name": n, "version": v}} for e, n, v in keys[i:i + BATCH]]}
        token = None
        # deps.dev answers 100 versions per page and says where to go on; answers are matched by key, not position.
        while True:
            page = post_json(f"{API}/v3alpha/versionbatch", {**body, "pageToken": token} if token else body)
            for resp in page.get("responses") or []:
                k = ((resp or {}).get("request") or {}).get("versionKey") or {}
                found = by_key.get((k.get("system"), k.get("name"), k.get("version")))
                if found and (resp or {}).get("version"):
                    _fill(out[found], resp["version"])
            token = page.get("nextPageToken")
            if not token:
                break
    return out


def _fill(info: dict, v: dict) -> None:
    repos = [p for p in v.get("relatedProjects") or [] if p.get("relationType") == "SOURCE_REPO"]
    # A signed build or publish attestation proves the link; plain metadata is only what the publisher typed.
    repos.sort(key=lambda p: p.get("relationProvenance") == "UNVERIFIED_METADATA")
    if repos:
        project = repos[0]["projectKey"]["id"]
        info["repo"] = project.removeprefix("github.com/")
        info["link"] = "claimed" if repos[0].get("relationProvenance") == "UNVERIFIED_METADATA" else "verified"
    info["licenses"] = v.get("licenses") or []
    info["advisories"] = [a.get("id") for a in v.get("advisoryKeys") or [] if a.get("id")]
    info["deprecated"] = bool(v.get("isDeprecated"))
    # The registry's own words, cut short: shown as a quote, never acted on.
    reason = " ".join((v.get("deprecatedReason") or "").split())[:160]
    info["deprecated_reason"] = reason or None if info["deprecated"] else None
    info["status"] = (v.get("projectStatus") or {}).get("status")


def manifest_name(path: str, text: str | None) -> str | None:
    """The package name a manifest declares: package.json, pyproject.toml ([project] or Poetry) or setup.cfg."""
    if not text:
        return None
    try:
        if path.endswith("package.json"):
            return json.loads(text).get("name")
        if path.endswith("pyproject.toml"):
            doc = tomllib.loads(text)
            return (doc.get("project") or {}).get("name") or ((doc.get("tool") or {}).get("poetry") or {}).get("name")
        if path.endswith("setup.cfg"):
            cfg = configparser.ConfigParser()
            cfg.read_string(text)
            return cfg.get("metadata", "name", fallback=None)
        if path.endswith("setup.py"):
            return _setup_py_name(text)
    except (ValueError, tomllib.TOMLDecodeError, configparser.Error, AttributeError):
        return None
    return None


def _setup_py_name(text: str) -> str | None:
    # setup(name="x"), or setup(name=NAME) with NAME = "x" in the same file; anything computed is not guessed.
    call = text[text.find("setup("):] if "setup(" in text else ""
    if m := re.search(r"""\bname\s*=\s*['"]([^'"]+)['"]""", call):
        return m.group(1)
    if m := re.search(r"\bname\s*=\s*([A-Za-z_]\w*)\s*[,)\n]", call):
        const = re.search(rf"""^\s*{m.group(1)}\s*=\s*['"]([^'"]+)['"]""", text, re.M)
        return const.group(1) if const else None
    return None


def _npm_directory(name: str, get_json) -> str | None:
    try:
        d = get_json(f"https://registry.npmjs.org/{quote(name, safe='@')}/latest")
        repo = d.get("repository") if isinstance(d, dict) else None
        raw = repo.get("directory") if isinstance(repo, dict) else None
    except Exception:  # noqa: BLE001
        return None
    # Publishers write anything here (numbers, lists): only a plain string is used.
    path = raw.strip().removeprefix("./").strip("/") if isinstance(raw, str) else ""
    # The folder goes into the GitHub query, so only plain path names are used.
    return path if SAFE_DIR.match(path) and ".." not in path.split("/") else None


def _candidates(eco: str, name: str, directory: str | None = None) -> list[str]:
    # Where projects keep the manifest that publishes the package, from the layouts of 33 real unconfirmed links.
    if eco == "pypi":
        folders = ["", f"{name}/", f"{name.replace('-', '_')}/", f"libs/{name}/", f"packages/{name}/", "python/", f"{name}-python/"]
        return list(dict.fromkeys([f"{d}{f}" for d in folders for f in ("pyproject.toml", "setup.py")] + ["setup.cfg"]))
    short = name.split("/")[-1]
    scoped = name.lstrip("@").replace("/", "-")
    first = [f"{directory}/package.json"] if directory else []
    return list(dict.fromkeys(first + ["package.json", f"packages/{short}/package.json", f"packages/{scoped}/package.json",
                               f"{short}/package.json", "npm/package.json"]))


def check_claims(infos: dict, gql, get_json=None) -> int:
    """Claimed GitHub links become "claimed_checked" when the repo's manifest names the package, else
    "claimed_unconfirmed"; about 1 GraphQL point per 25 repos. With get_json, npm's repository.directory is looked in
    first (monorepos). Returns how many were checked."""
    todo = [i for i in infos.values() if i.get("link") == "claimed" and i.get("repo") and "/" in i["repo"]
            and all(SAFE.match(part) for part in i["repo"].split("/", 1))]
    for i in [x for x in infos.values() if x.get("link") == "claimed" and x not in todo]:
        i["link"] = "claimed_unconfirmed"
    npm = [i for i in todo if i["ecosystem"] == "npm"] if get_json is not None else []
    with ThreadPoolExecutor(16) as pool:
        for info, path in zip(npm, pool.map(lambda i: _npm_directory(i["package"], get_json), npm)):
            info["directory"] = path
    checked = 0
    for start in range(0, len(todo), CLAIM_BATCH):
        chunk = todo[start:start + CLAIM_BATCH]
        lines, files = [], {}
        for r, info in enumerate(chunk):
            owner, name = info["repo"].split("/", 1)
            lines.append(f'  r{r}: repository(owner: "{owner}", name: "{name}") {{')
            for f, path in enumerate(_candidates(info["ecosystem"], info["package"], info.get("directory"))):
                files[(r, f)] = path
                lines.append(f'    f{f}: object(expression: "HEAD:{path}") {{ ... on Blob {{ text }} }}')
            lines.append("  }")
        query = "query {\n  rateLimit { cost remaining resetAt }\n" + "\n".join(lines) + "\n}"
        try:
            data = gql.query(query, {}, partial=True).data
        except (GraphQLError, RateLimited):
            # The rest stay "claimed" (not yet checked) and are tried on the next run.
            return checked
        checked += len(chunk)
        for r, info in enumerate(chunk):
            repo = data.get(f"r{r}") or {}
            names = {manifest_name(path, ((repo.get(f"f{f}") or {}).get("text"))) for (rr, f), path in files.items() if rr == r}
            match = {_norm(info["ecosystem"], n) for n in names if n} & {_norm(info["ecosystem"], info["package"])}
            info["link"] = "claimed_checked" if match else "claimed_unconfirmed"
    return checked


MAX_AGE_DAYS = 7
# How releases are counted; answers from an older rule are looked up again (2: pre-releases no longer count).
RELEASE_RULE = 2


def refresh_map(packages: list[tuple[str, str]], previous: dict, now: datetime, gql=None, budget_s: float = 600,
                lookup=lookup_packages, check=check_claims, get_json=http_get_json) -> dict:
    """Yesterday's map with new and week-old packages looked up again (within the time budget) and their claimed
    links checked when a GitHub token is at hand; a package skipped by the budget keeps its last answer."""
    stamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    stale_before = (now - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    keep, todo = {}, []
    for eco, name in dict.fromkeys(packages):
        old = previous.get(f"{eco}:{name}")
        # Answers built on a pre-release (before stable versions were preferred) are asked again.
        if (old and (old.get("fetched_at") or "") >= stale_before and not PRERELEASE.search(old.get("version") or "")
                and old.get("release_rule", 1) >= RELEASE_RULE):
            keep[f"{eco}:{name}"] = old
        else:
            todo.append((eco, name))
            if old:
                keep[f"{eco}:{name}"] = old
    fresh = lookup(todo, now=now, budget_s=budget_s)
    if gql is not None:
        check(fresh, gql, get_json=get_json)
    for (eco, name), info in fresh.items():
        keep[f"{eco}:{name}"] = {**info, "fetched_at": stamp}
    return keep
