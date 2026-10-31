"""Supply chain from the repo's own dependency graph: the SBOM from GitHub's asynchronous report (the synchronous endpoint
closes on 13 November 2026), each package's licence from deps.dev (GitHub's SBOM mostly leaves licences blank), a licence
policy with decisions, licence drift between quarterly snapshots, and OpenSSF Scorecard drops for the projects behind the
packages. Everything is kept in deps/supply/ on the data branch, so the history outlives both services' caches."""
import fnmatch
import gzip
import json
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote, unquote

import httpx

from stackvitals.ci.api import APIError, OutOfBudget
from stackvitals.core.time import iso

SYSTEMS = {"npm": "NPM", "pypi": "PYPI", "maven": "MAVEN", "golang": "GO", "cargo": "CARGO", "gem": "RUBYGEMS", "nuget": "NUGET"}
ACTIONS = "ACTIONS"  # workflow actions: not in deps.dev, and the project behind one is its own repo
DEPS_DEV = "https://api.deps.dev/v3"
SCORECARD = "https://api.scorecard.dev/projects"
UNSET = {"", "NOASSERTION", "NONE"}
POLLS = 30
LOOKUPS, SCORES = 200, 40  # the most deps.dev and Scorecard calls one run makes; the rest wait for the next run
LOW_SCORE, DROP = 4.0, 1.0
SCORE_EVERY = timedelta(days=7)
HISTORY = 12


class SupplyError(Exception):
    """A plain sentence for the job summary and the page."""


class SupplyRefused(SupplyError):
    """GitHub said no (the dependency graph is off, or no access): asking again soon won't change it."""


def _purl(text: str) -> tuple[str | None, str, str] | None:
    """(system, package name as deps.dev spells it, version) from a package URL; workflow actions are ACTIONS."""
    found = re.match(r"pkg:([^/]+)/(.+?)@([^?#]+)", text or "")
    if not found:
        return None
    kind, path, version = found.group(1).lower(), unquote(found.group(2)), unquote(found.group(3))
    if kind == "githubactions":
        return ACTIONS, path, version
    if kind == "maven":
        path = path.replace("/", ":", 1)
    elif kind == "pypi":
        path = re.sub(r"[-_.]+", "-", path).lower()
    return SYSTEMS.get(kind), path, version


def parse_spdx(doc: dict) -> list[dict]:
    """The packages an SPDX document lists, with the licence GitHub gave each one when it gave one."""
    doc = doc.get("sbom", doc)
    # The repo itself is listed too (with a pkg:github purl): it is what the document describes, not a dependency.
    itself = {r.get("relatedSpdxElement") for r in doc.get("relationships") or [] if r.get("relationshipType") == "DESCRIBES"}
    out, seen = [], set()
    for p in doc.get("packages") or []:
        ref = next((r.get("referenceLocator") for r in p.get("externalRefs") or []
                    if r.get("referenceType") == "purl"), None)
        parsed = _purl(ref) if ref and p.get("SPDXID") not in itself else None
        if not parsed or ref in seen:
            continue
        seen.add(ref)
        system, name, version = parsed
        licence = next((x for x in (p.get("licenseConcluded"), p.get("licenseDeclared")) if x and x not in UNSET), None)
        out.append({"purl": ref, "system": system, "name": name, "version": version, "licences": [licence] if licence else []})
    return out


def sbom(api, polls: int = POLLS) -> list[dict]:
    """The default branch's SBOM: ask GitHub for a report, then wait until it is ready."""
    try:
        made = api._get(f"/repos/{api.repo}/dependency-graph/sbom/generate-report")
        path = (made or {}).get("sbom_url", "").split("api.github.com", 1)[-1]
        for _ in range(polls):
            # 201 or 202 (with a "{}" body) while the report is being made; 200 once the redirect reached the file.
            status, body = api.fetch(path)
            if status == 200 and body:
                return parse_spdx(json.loads(body))
            api.sleep(1)
    except APIError as exc:
        # The status, not the start of the message: a long repo path once hid it.
        status = re.search(r"HTTP \d{3}", str(exc))
        raise SupplyRefused(f"GitHub would not make an SBOM for this repo ({status.group(0) if status else str(exc)[-80:]}): "
                          "turn on the dependency graph (Settings, Code security); the workflow needs contents: read.") from None
    except (OutOfBudget, ValueError) as exc:
        raise SupplyError(f"The SBOM could not be read this time ({type(exc).__name__}); the next run tries again.") from None
    raise SupplyError(f"GitHub's SBOM report wasn't ready after {polls} tries; the next run tries again.")


class LicenceCache:
    """deps.dev's answer per package version (licences and the project behind it), kept: a version never changes."""

    def __init__(self, root: Path):
        self.path = Path(root) / "deps" / "supply" / "lookups.json.gz"
        try:
            self.data = json.loads(gzip.decompress(self.path.read_bytes()))
        except (OSError, ValueError, EOFError):
            self.data = {}
        self.changed = False

    def put(self, purl: str, value: dict) -> None:
        self.data[purl] = value
        self.changed = True

    def save(self) -> None:
        if self.changed:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_bytes(gzip.compress(json.dumps(self.data, sort_keys=True, separators=(",", ":")).encode(), mtime=0))
            self.changed = False


def _lookup(p: dict, client: httpx.Client, cache: LicenceCache | None) -> dict | None:
    if p.get("system") == ACTIONS:
        return {"l": [], "p": "github.com/" + "/".join(p["name"].split("/")[:2])}
    if cache is not None and p["purl"] in cache.data:
        return cache.data[p["purl"]]
    if not p.get("system"):
        return None
    url = f"{DEPS_DEV}/systems/{p['system']}/packages/{quote(p['name'], safe='')}/versions/{quote(p['version'], safe='')}"
    try:
        resp = client.get(url)
    except httpx.HTTPError:
        return None
    if resp.status_code not in (200, 404):
        return None
    body = resp.json() if resp.status_code == 200 else {}
    source = next((r.get("projectKey", {}).get("id") for r in body.get("relatedProjects") or []
                   if r.get("relationType") == "SOURCE_REPO" and r.get("projectKey", {}).get("id")), None)
    value = {"l": [x for x in body.get("licenses") or [] if x and x not in UNSET], "p": source}
    if cache is not None:
        cache.put(p["purl"], value)
    return value


def licences(packages: list[dict], client: httpx.Client, cache: LicenceCache, limit: int = LOOKUPS) -> dict[str, list[str]]:
    """Each package's licences: deps.dev's, else GitHub's; looked up once per version and kept."""
    out, asked = {}, 0
    for p in packages:
        known = p["purl"] in cache.data
        if not known and (p.get("system") in (None, ACTIONS) or asked >= limit):
            out[p["purl"]] = p.get("licences") or []
            continue
        asked += 0 if known else 1
        found = _lookup(p, client, cache) or {}
        out[p["purl"]] = found.get("l") or p.get("licences") or []
    return out


def _denied(expression: str, deny: list[str]) -> bool:
    """A choice ("A OR B") is fine when one choice is allowed; "A AND B" needs every part allowed; AND binds tighter than
    OR and parentheses group, as SPDX says; "X WITH exception" is judged as X."""
    tokens, at = re.findall(r"\(|\)|[^\s()]+", expression), 0

    def peek() -> str:
        return tokens[at].upper() if at < len(tokens) else ""

    def either() -> bool:  # allowed when any choice is allowed
        nonlocal at
        ok = both()
        while peek() == "OR":
            at += 1
            ok = both() or ok
        return ok

    def both() -> bool:  # allowed when every part is allowed
        nonlocal at
        ok = one()
        while peek() == "AND":
            at += 1
            ok = one() and ok
        return ok

    def one() -> bool:
        nonlocal at
        if peek() == "(":
            at += 1
            ok = either()
            at += peek() == ")"
            return ok
        name = tokens[at] if at < len(tokens) else ""
        at += 1
        if peek() == "WITH":
            at += 2
        return not any(fnmatch.fnmatchcase(name, pattern) for pattern in deny)

    return not either()


# OSV's ecosystem names as deps.dev's systems, for a pull request's new packages.
OSV_SYSTEMS = {"npm": "NPM", "PyPI": "PYPI", "Maven": "MAVEN", "Go": "GO", "crates.io": "CARGO", "RubyGems": "RUBYGEMS", "NuGet": "NUGET"}


def pr_licences(new_packages: list, deny: list[str], client: httpx.Client, limit: int = 60) -> list[dict]:
    """The packages a pull request adds whose licence the repo's policy denies, looked up on deps.dev."""
    out = []
    for eco, name, version in new_packages[:limit]:
        system = OSV_SYSTEMS.get(eco)
        if not system:
            continue
        found = _lookup({"system": system, "name": name, "version": version, "purl": f"{eco}/{name}@{version}"}, client, None) or {}
        expression = _joined(found.get("l") or [])
        if expression and _denied(expression, deny):
            out.append({"ecosystem": eco, "package": name, "version": version, "licence": expression})
    return out


def policy(packages: list[dict], deny: list[str], accepted: set[str] = frozenset()) -> dict:
    """Packages whose licence the repo's policy denies (minus the ones a decision accepted), how many have no known
    licence, and how many use each licence."""
    denied, kept, by_licence, unknown = [], [], Counter(), 0
    for p in packages:
        if p.get("system") == ACTIONS:
            continue  # workflow actions run in CI and never ship with the product
        if not p.get("licences"):
            unknown += 1
            continue
        expression = _joined(p["licences"])  # several licences all apply, each kept whole in parentheses
        by_licence[expression] += 1
        if deny and _denied(expression, deny):
            row = {"name": p["name"], "version": p["version"], "system": p.get("system"), "purl": p["purl"], "licence": expression}
            (kept if p["name"] in accepted else denied).append(row)
    return {"denied": denied, "accepted": kept, "unknown": unknown, "by_licence": dict(by_licence.most_common())}


def _quarter(when: datetime) -> str:
    return f"{when.year}-Q{(when.month - 1) // 3 + 1}"


class SupplyStore:
    """Quarterly licence snapshots and each project's Scorecard history, under deps/supply/."""

    def __init__(self, root: Path):
        self.dir = Path(root) / "deps" / "supply"
        self.scores, self.asked = self._read("scorecards.json"), self._read("asked.json")

    def _read(self, name: str) -> dict:
        try:
            return json.loads((self.dir / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def snapshot(self, packages: list[dict], when: datetime) -> None:
        rows = sorted([p.get("system") or "", p["name"], p["version"], p.get("licences") or []] for p in packages)
        path = self.dir / "snapshots" / f"{_quarter(when)}.json.gz"
        data = gzip.compress(json.dumps(rows, separators=(",", ":")).encode(), mtime=0)
        if not path.exists() or path.read_bytes() != data:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def quarters(self) -> list[str]:
        folder = self.dir / "snapshots"
        return sorted(p.name.split(".")[0] for p in folder.glob("*.json.gz")) if folder.is_dir() else []

    def load(self, quarter: str) -> list:
        return json.loads(gzip.decompress((self.dir / "snapshots" / f"{quarter}.json.gz").read_bytes()))

    def save(self) -> None:
        for name, data in (("scorecards.json", self.scores), ("asked.json", self.asked)):
            text = json.dumps(data, indent=1, sort_keys=True)
            path = self.dir / name
            if not path.exists() or path.read_text(encoding="utf-8") != text:
                self.dir.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8", newline="\n")


def drift(store: SupplyStore, now: datetime) -> list[dict]:
    """Packages whose licence changed between the last two quarterly snapshots (a version bump that also relicensed)."""
    quarters = [q for q in store.quarters() if q <= _quarter(now)]
    if len(quarters) < 2:
        return []
    before, after = quarters[-2], quarters[-1]
    old, new = _newest(store.load(before)), _newest(store.load(after))
    out = []
    for (s, n), ls in new.items():
        was, now_ = _joined(old.get((s, n))), _joined(ls)
        if was and now_ and was != now_:
            out.append({"name": n, "system": s or None, "from": was, "to": now_, "from_quarter": before, "to_quarter": after})
    return sorted(out, key=lambda x: (x["system"] or "", x["name"]))


def _version_key(version: str) -> list:
    # Natural order (2.0 < 10.0), comparable whatever mix of digits and letters a version has.
    return [(1, int(x), "") if x.isdigit() else (0, 0, x) for x in re.findall(r"\d+|\D+", version or "")]


def _newest(rows: list) -> dict:
    # Each package's licences at its newest version in a snapshot: a repo using two versions is not drift.
    best = {}
    for s, n, v, ls in rows:
        if (s, n) not in best or _version_key(v) > _version_key(best[(s, n)][0]):
            best[(s, n)] = (v, ls)
    return {key: ls for key, (_v, ls) in best.items()}


def _joined(licences: list | None) -> str | None:
    if not licences:
        return None
    return licences[0] if len(licences) == 1 else " AND ".join(f"({x})" for x in licences)


EVERY = timedelta(days=6)  # once a week on the schedule; a manual run reads it at once


def supply_step(ws, env: dict, now: datetime, make_api=None, client: httpx.Client | None = None) -> dict | None:
    """The supply chain page: the SBOM, licences, the repo's licence policy and decisions, drift and Scorecard drops,
    published as docs/supply.json. Trouble (the dependency graph off, GitHub busy) is said and never fails the job."""
    from stackvitals.core.config import parse
    from stackvitals.core.decisions import Store
    from stackvitals.core.store import published, write_if_changed
    cfg = ws.cache.get("settings") or parse("")[0]
    state_path = ws.path / "deps" / "supply" / "state.json"
    try:
        last = json.loads(state_path.read_text(encoding="utf-8")).get("last")
    except (OSError, ValueError):
        last = None
    if env.get("GITHUB_EVENT_NAME") != "workflow_dispatch" and last and last > iso(now - EVERY):
        return None
    if make_api is None:
        from stackvitals.ci.api import ActionsAPI as make_api
    api = make_api(env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN"), ws.repo, max_requests=60)
    try:
        packages = sbom(api)
    except SupplyError as exc:
        if isinstance(exc, SupplyRefused):
            # Remembered, so a dependency graph that's off is asked about weekly, not on every 3-hourly run.
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"last": iso(now), "error": str(exc)}), encoding="utf-8", newline="\n")
            exc = f"{exc} Asked again next week, or now on a manual run."
        ws.notes.append(f"Supply chain: {exc}")
        return {"error": str(exc)}
    own = client is None
    client = client or httpx.Client(timeout=20, headers={"User-Agent": "stackvitals"})
    cache, store = LicenceCache(ws.path), SupplyStore(ws.path)
    outside = cfg["deps"].get("outside_lookups", True)
    try:
        # With outside lookups off, no dependency name leaves the repo: GitHub's licences and what is cached are kept.
        found = licences(packages, client, cache, limit=LOOKUPS if outside else 0)
        for p in packages:
            p["licences"] = found.get(p["purl"]) or []
        store.snapshot(packages, now)
        state = Store(ws.path).state(now.date())
        accepted = {key.split(":", 1)[1] for key, d in state.items() if key.startswith("package:") and d.get("verb") == "accept"}
        deny = cfg["deps"]["licenses"]["deny"]
        rules = policy(packages, deny, accepted)
        cards = scorecards(packages, client, store, now, cache, lookups=0, limit=SCORES if outside else 0)
        minimum = cfg["deps"]["policy"]["min_scorecard"]
        cards["below_policy"] = below_policy(store.scores, cards.pop("names"), minimum, accepted)
    finally:
        # Whatever was looked up is kept even if a later step fails, so the next run starts further on.
        cache.save()
        store.save()
        if own:
            client.close()
    reach = _reachability(env.get("STACKVITALS_GOVULNCHECK"))
    # Runtimes (Node, Python, PHP, Ruby, Go) against their support dates: their flaws are not package advisories.
    found_runtimes = None
    if outside:
        from stackvitals.deps.runtimes import runtimes
        try:
            with httpx.Client(timeout=20, headers={"User-Agent": "stackvitals"}) as eol:
                found_runtimes = runtimes(api, api._get(f"/repos/{ws.repo}").get("default_branch") or "main", eol)
        except Exception as exc:  # noqa: BLE001 - the rest of the page still publishes
            ws.notes.append(f"Supply chain: runtime versions not read ({type(exc).__name__}).")
    out = {"generated": iso(now), "packages": len(packages), **({"reachability": reach} if reach else {}),
           "systems": dict(Counter(p.get("system") or "OTHER" for p in packages).most_common()),
           # Scorecard is shown as one input, never part of a package's verdict.
           "policy": {"deny": deny, "min_scorecard": minimum}, "licences": rules, "drift": drift(store, now),
           "scorecards": cards, "outside_lookups": outside, **({"runtimes": found_runtimes} if found_runtimes is not None else {})}
    docs = ws.path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    write_if_changed(docs / "supply.json", published(out))
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"last": iso(now)}), encoding="utf-8", newline="\n")
    return {"packages": len(packages), "denied": len(rules["denied"]), "drops": len(cards["drops"])}


def _reachability(path: str | None) -> dict | None:
    """govulncheck's findings when the workflow ran it and passed its file (the govulncheck-json input)."""
    if not path:
        return None
    from pathlib import Path

    from stackvitals.deps.reach import read_govulncheck
    try:
        return read_govulncheck(Path(path).read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {"error": f"{path} couldn't be read; check the govulncheck step ran before StackVitals."}
    except (ValueError, TypeError, KeyError, AttributeError):
        return {"error": f"{path} isn't govulncheck's JSON output (run it with -json)."}


def below_policy(scores: dict, names: dict, minimum: float | None, accepted: set[str]) -> list[dict]:
    """Projects whose newest Scorecard is under the repo's min_scorecard, minus packages a decision accepted."""
    if minimum is None:
        return []
    out = []
    for project, history in sorted(scores.items()):
        packages = sorted(n for n in names.get(project, ()) if n not in accepted)
        if history and history[-1][1] < minimum and packages:
            out.append({"project": project, "score": history[-1][1], "packages": packages})
    return sorted(out, key=lambda x: x["score"])


def _score(client: httpx.Client, project: str) -> tuple[str, float] | None:
    try:
        resp = client.get(f"{SCORECARD}/{project}")
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    body = resp.json()
    score = body.get("score")
    return (str(body.get("date") or "")[:10], float(score)) if isinstance(score, (int, float)) else None


def scorecards(packages: list[dict], client: httpx.Client, store: SupplyStore, now: datetime, cache: LicenceCache | None = None,
               limit: int = SCORES, lookups: int = LOOKUPS) -> dict:
    """The OpenSSF Scorecard of each project behind the packages, kept over time: drops of a point or more since the last
    score, and projects scoring under 4. Only `lookups` new deps.dev calls (the step passes 0: the licence pass already
    looked packages up), and the projects asked longest ago go first, so every project gets its turn."""
    projects = {}
    for p in packages:
        if p.get("system") == ACTIONS or cache is not None and p["purl"] in cache.data:
            found = _lookup(p, client, cache)
        elif lookups > 0 and p.get("system"):
            lookups -= 1
            found = _lookup(p, client, cache)
        else:
            continue
        if found and (found.get("p") or "").startswith("github.com/"):
            projects.setdefault(found["p"], []).append(p["name"])
    week_ago, today = iso(now - SCORE_EVERY)[:10], now.date().isoformat()
    due = [p for p in projects if (store.asked.get(p) or "") <= week_ago]
    for project in sorted(due, key=lambda p: (store.asked.get(p) or "", p))[:limit]:
        store.asked[project] = today  # 404s and unchanged answers count as asked, so they wait a week too
        history = store.scores.get(project) or []
        got = _score(client, project)
        if got and (not history or history[-1][0] != got[0]):
            store.scores[project] = (history + [list(got)])[-HISTORY:]
    drops, low = [], []
    for project, names in projects.items():
        history = store.scores.get(project) or []
        if len(history) >= 2 and history[-2][1] - history[-1][1] >= DROP:
            drops.append({"project": project, "before": history[-2][1], "after": history[-1][1], "since": history[-2][0],
                          "packages": sorted(set(names))})
        if history and history[-1][1] < LOW_SCORE:
            low.append({"project": project, "score": history[-1][1], "packages": sorted(set(names))})
    return {"checked": sum(1 for p in projects if store.scores.get(p)), "projects": len(projects),
            "drops": sorted(drops, key=lambda x: x["after"] - x["before"]), "low": sorted(low, key=lambda x: x["score"]),
            "names": {p: sorted(set(n)) for p, n in projects.items()}}
