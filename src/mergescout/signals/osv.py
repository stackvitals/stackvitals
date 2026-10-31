"""Vulnerability history per package from OSV (free, no key): every advisory ever, merged across aliases (GHSA, PYSEC,
CVE are often the same flaw), with the ones still unfixed and any malware record. Records are cached by their modified
time, so a daily run fetches only new or changed ones."""
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import quote

from mergescout.signals.bumps import _norm
from mergescout.signals.deps_map import http_get_json, http_post_json

API = "https://api.osv.dev"
ECOSYSTEMS = {"pypi": "PyPI", "npm": "npm"}
QUERY_BATCH = 1000
# A first run would fetch every advisory at once (about 2,300 for 300 packages took 3 minutes); later runs only new ones.
MAX_FETCH = 4000
RANK = {"CRITICAL": 4, "HIGH": 3, "MODERATE": 2, "MEDIUM": 2, "LOW": 1}


def _ids(packages: list[tuple[str, str]], post_json) -> dict[str, dict[str, str]]:
    # Advisory ids and their modified time per package; a package with many advisories answers in pages.
    out = {}
    wanted = [(eco, name) for eco, name in packages if eco in ECOSYSTEMS]
    for i in range(0, len(wanted), QUERY_BATCH):
        chunk = wanted[i:i + QUERY_BATCH]
        queries = [{"package": {"name": name, "ecosystem": ECOSYSTEMS[eco]}} for eco, name in chunk]
        results = post_json(f"{API}/v1/querybatch", {"queries": queries}).get("results") or []
        for (eco, name), query, result in zip(chunk, queries, results):
            found = {v["id"]: v.get("modified") for v in (result or {}).get("vulns") or []}
            token = (result or {}).get("next_page_token")
            while token:
                more = (post_json(f"{API}/v1/querybatch", {"queries": [{**query, "page_token": token}]}).get("results") or [{}])[0]
                found.update({v["id"]: v.get("modified") for v in (more or {}).get("vulns") or []})
                token = (more or {}).get("next_page_token")
            out[f"{eco}:{name}"] = found
    return out


def _facts(record: dict, keys: set[str]) -> dict:
    # The few fields the history needs; the advisory text is not kept.
    pkgs, bounds, bad, spans = {}, {}, {}, {}
    mal = _is_malware(record)
    for a in record.get("affected") or []:
        pkg = a.get("package") or {}
        eco = next((k for k, v in ECOSYSTEMS.items() if v == pkg.get("ecosystem")), None)
        key = f"{eco}:{_norm(eco, pkg.get('name') or '')}" if eco else None
        if key in keys:
            events = [e for r in a.get("ranges") or [] for e in r.get("events") or []]
            pkgs[key] = pkgs.get(key, False) or any("fixed" in e for e in events)
            # "last_affected" bounds the range without naming a fix: newer releases are not affected.
            bounds[key] = bounds.get(key, []) + [e["last_affected"] for e in events if e.get("last_affected")]
            # Each [introduced, fixed) span, so a PR's version can be checked and the fixing version named.
            for r in a.get("ranges") or []:
                if r.get("type") in ("ECOSYSTEM", "SEMVER"):
                    start = None
                    for e in r.get("events") or []:
                        if "introduced" in e:
                            start = e["introduced"]
                        elif "fixed" in e and start is not None:
                            spans.setdefault(key, []).append([start, e["fixed"]])
                            start = None
                        elif "last_affected" in e and start is not None:
                            # Up to and including that version, with no fix named.
                            spans.setdefault(key, []).append([start, e["last_affected"], True])
                            start = None
                    if start is not None:
                        spans.setdefault(key, []).append([start, None])
            if mal:
                # A malware record lists the bad versions; a range open from "0" means every version (OSV's rule).
                every = any(e.get("introduced") == "0" for e in events) and not any("fixed" in e or "last_affected" in e
                                                                                    for e in events)
                bad[key] = ["all"] if every or "all" in bad.get(key, []) else \
                    sorted(set(bad.get(key, [])) | set(a.get("versions") or []), key=_version_key)[-50:]
    # OSV keeps CVEs the supplier disputes and says so in the text; only the flag is kept.
    text = f"{record.get('summary') or ''} {record.get('details') or ''}".lower()
    return {"rv": RECORD, "id": record.get("id"), "aliases": record.get("aliases") or [], "published": record.get("published"),
            "modified": record.get("modified"), "withdrawn": bool(record.get("withdrawn")),
            "severity": ((record.get("database_specific") or {}).get("severity") or "").upper() or None, "pkgs": pkgs,
            "bounds": bounds, "ranges": spans, "disputed": "disputed" in text, **({"bad": bad} if mal else {})}


def _is_malware(record: dict) -> bool:
    return any(n.startswith("MAL-") for n in (record.get("id") or "", *(record.get("aliases") or [])))


# The record format: a record built by older code is read again (last_affected spans came in version 2).
RECORD = 2
# Pre-releases sort before their release and post-releases after it (PEP 440 and semver agree on that much).
PHASES = {"dev": 0, "a": 1, "alpha": 1, "b": 2, "beta": 2, "c": 3, "rc": 3, "pre": 3, "preview": 3, "post": 5}


def version_key(v: str | None) -> tuple:
    """(epoch, release padded to 4, phase, number): 2.0.0rc1 < 2.0.0 < 2.0.0.post1, 1!0.1 > 9.9."""
    s = (v or "").strip().lower().removeprefix("v")
    epoch = 0
    if "!" in s:
        head, s = s.split("!", 1)
        epoch = int(head) if head.isdigit() else 0
    m = re.match(r"(\d+(?:\.\d+)*)(.*)", s)
    if not m:
        return (epoch, (0, 0, 0, 0), 4, 0)
    release = tuple(int(x) for x in m.group(1).split(".")[:4])
    release += (0,) * (4 - len(release))
    rest = m.group(2).split("+", 1)[0]
    tag = re.search(r"(dev|alpha|beta|preview|pre|post|rc|a|b|c)[.-]?(\d*)", rest)
    if tag:
        return (epoch, release, PHASES[tag.group(1)], int(tag.group(2) or 0))
    # Any other suffix after a dash (1.0.0-next.3) is a semver pre-release.
    return (epoch, release, 3 if rest.startswith("-") else 4, 0)


def _version_key(v: str) -> tuple:
    return version_key(v)


def _cves(group: list[dict]) -> list[str]:
    return sorted({n for x in group for n in (x["id"], *x["aliases"]) if n.startswith("CVE-")})


def _summary(key: str, facts: list[dict], now: datetime, exploits: dict | None = None) -> dict:
    live = [f for f in facts if not f["withdrawn"] and key in f["pkgs"]]
    # One flaw under several ids (aliases) counts once: group ids that share any id or alias.
    groups, seen = [], {}
    for f in live:
        names = {f["id"], *f["aliases"]}
        hit = {seen[n] for n in names if n in seen}
        merged = [f]
        for g in sorted(hit, reverse=True):
            merged += groups.pop(g)
        groups.append(merged)
        seen = {n: i for i, g in enumerate(groups) for x in g for n in (x["id"], *x["aliases"])}
    since = (now - timedelta(days=730)).strftime("%Y-%m-%d")
    recent = (now - timedelta(days=90)).strftime("%Y-%m-%d")
    severity, out = {}, {"advisories": len(groups), "last_2y": 0, "last_90d": 0, "unfixed": 0, "latest": None, "ids": []}
    malware, last_affected, bad = set(), set(), set()
    out["disputed"] = 0
    kev, epss_open, epss_max = [], None, None
    affects = []
    open_label = None
    for g in groups:
        first = min((x["published"] or "")[:10] for x in g)
        out["last_2y"] += first >= since
        out["last_90d"] += first >= recent
        # A malware record lists bad versions and never has a fix; it is reported as malware, not as unfixed.
        mal = {n for x in g for n in (x["id"], *x["aliases"]) if n.startswith("MAL-")}
        malware |= mal
        if mal:
            bad |= {v for x in g for v in (x.get("bad") or {}).get(key, [])}
        fixed = any(x["pkgs"][key] for x in g)
        bound = [v for x in g for v in (x.get("bounds") or {}).get(key, [])]
        if mal or fixed:
            pass
        elif any(x.get("disputed") for x in g):
            out["disputed"] += 1
        elif bound:
            # Open only while the newest release is inside the bound; the dossier compares with the current version.
            last_affected.add(max(bound, key=_version_key))
        else:
            out["unfixed"] += 1
        # Exploited in the wild (KEV), and the chance of it (EPSS): an open advisory's matters most.
        for cve in _cves(g) if exploits is not None else ():
            e = exploits.get(cve) or {}
            if e.get("kev"):
                kev.append({"id": cve, "fixed": bool(fixed)})
            if "epss" in e:
                score = {"id": cve, "score": e["epss"], "percentile": e.get("percentile")}
                epss_max = max(epss_max or score, score, key=lambda s: s["score"])
                if not (mal or fixed or bound):
                    epss_open = max(epss_open or score, score, key=lambda s: s["score"])
        spans = [s for x in g for s in (x.get("ranges") or {}).get(key, [])]
        label = max((x["severity"] for x in g if x["severity"]), key=lambda s: RANK.get(s, 0), default=None)
        disputed = any(x.get("disputed") for x in g)
        if spans and not mal:
            affects.append({"id": g[0]["id"], "ranges": spans, "severity": label, "disputed": disputed})
        out["latest"] = max(out["latest"] or "", first) or None
        if label:
            severity[label] = severity.get(label, 0) + 1
            # The worst advisory still open (no fix, or a range ending at a bound), for a repo's severity policy.
            if not (mal or fixed or bound or disputed) and RANK.get(label, 0) > RANK.get(open_label or "", 0):
                open_label = label
    out["severity"], out["open_severity"] = severity, open_label
    out["affects"] = affects
    out["malware"], out["malware_ids"] = bool(malware), sorted(malware)
    out["malware_versions"] = ["all"] if "all" in bad else sorted(bad, key=_version_key)[-50:]
    out["last_affected"] = sorted(last_affected, key=_version_key)
    out["ids"] = [g[0]["id"] for g in sorted(groups, key=lambda g: min(x["published"] or "" for x in g), reverse=True)[:5]]
    if exploits is not None:
        out["kev"] = sorted({k["id"]: k for k in kev}.values(), key=lambda k: k["id"])
        out["epss_open"], out["epss_max"] = epss_open, epss_max
    return out


def _fetch(get_json, advisory_id: str) -> dict | None:
    # A record lost after retries is left out of the cache, so the next run asks for it again.
    try:
        return get_json(f"{API}/v1/vulns/{quote(advisory_id, safe='')}")
    except Exception:  # noqa: BLE001
        return None


def refresh_vulns(packages: list[tuple[str, str]], previous: dict, now: datetime, post_json=http_post_json,
                  get_json=http_get_json, workers: int = 8, max_fetch: int = MAX_FETCH, exploits=None) -> dict:
    """{"records": cached facts by advisory id, "packages": history per "ecosystem:name"}; only new or changed
    advisories are fetched again. exploits: a lookup cves -> {cve: {"epss", "percentile", "kev"}} (signals.exploits);
    without one, no exploit evidence is added."""
    keys = {f"{eco}:{name}" for eco, name in packages if eco in ECOSYSTEMS}
    ids = _ids(packages, post_json)
    old = previous.get("records") or {}
    # Records cached before ranges' bounds (or malware versions) were kept are read once more.
    stale = lambda r: r.get("rv") != RECORD or (_is_malware(r) and "bad" not in r)  # noqa: E731
    todo = sorted({i for found in ids.values() for i, mod in found.items()
                   if (old.get(i) or {}).get("modified") != mod or stale(old.get(i) or {})})
    complete = len(todo) <= max_fetch
    todo = todo[:max_fetch]
    with ThreadPoolExecutor(workers) as pool:
        fetched = list(pool.map(lambda i: _fetch(get_json, i), todo))
    records = {i: old[i] for found in ids.values() for i in found if i in old and i not in todo}
    # The cache keeps the batch answer's modified time: the record itself may spell it with other precision.
    modified = {i: mod for found in ids.values() for i, mod in found.items()}
    records.update({i: {**_facts(r, keys), "modified": modified[i]} for i, r in zip(todo, fetched) if r})
    found = None
    if exploits is not None:
        cves = sorted({n for r in records.values() for n in (r["id"], *r["aliases"]) if n.startswith("CVE-")})
        found = exploits(cves) or {}
    packages_out = {key: _summary(key, [records[i] for i in ids.get(key, {}) if i in records], now, found)
                    for key in sorted(keys)}
    # Not complete: some advisories wait for the next run, so counts may still grow.
    out = {"built_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "complete": complete, "records": records, "packages": packages_out}
    if found is not None:
        out["exploits"] = {"cves": len(cves), "scored": sum("epss" in e for e in found.values()),
                           "kev": sum(bool(e.get("kev")) for e in found.values())}
    return out
