"""Known vulnerabilities in the GitHub Actions a repo's workflows use (OSV's "GitHub Actions" ecosystem: tj-actions/
changed-files and the like), which no lockfile lists. Actions used by tag are checked; ones pinned to a full commit
can't be matched to a version, and are counted, not guessed."""
import re

import yaml

OSV_BATCH = "https://api.osv.dev/v1/querybatch"
USES = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)(/[^@]*)?@(.+)$")
SHA = re.compile(r"^[0-9a-f]{40}$")


def uses_in(files: dict[str, str]) -> list[dict]:
    """Every action a workflow uses: {"action", "ref", "file"}; local actions and Docker images left out."""
    out = []
    for path, text in files.items():
        try:
            doc = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        for job in ((doc or {}).get("jobs") or {}).values() if isinstance(doc, dict) else []:
            refs = [job.get("uses")] if isinstance(job, dict) and job.get("uses") else []
            refs += [s.get("uses") for s in (job.get("steps") or []) if isinstance(s, dict) and s.get("uses")] if isinstance(job, dict) else []
            for ref in refs:
                m = USES.match(str(ref))
                if m:
                    out.append({"action": m.group(1), "ref": m.group(3), "file": path})
    return out


def version_of(ref: str) -> str | None:
    """The version a tag names (v4.2.0 and v4 read as 4.2.0 and 4), None for a commit or a branch."""
    if SHA.match(ref):
        return None
    m = re.fullmatch(r"v?(\d+(?:\.\d+){0,2})", ref)
    return m.group(1) if m else None


def _key(v: str) -> list:
    return [int(p) if p.isdigit() else 0 for p in str(v).split(".")[:3]] + [0] * (3 - len(str(v).split(".")[:3]))


def affected(version: str, ranges: list[dict]) -> bool:
    """Whether a tag's version falls in an advisory's ECOSYSTEM ranges. A major-only tag (v4) moves to the newest 4.x,
    so it counts only when no 4.x release is fixed."""
    major_only = "." not in version
    for r in ranges or []:
        if r.get("type") != "ECOSYSTEM":
            continue
        lo, fixed, last = "0", None, None
        for e in r.get("events") or []:
            lo = e.get("introduced", lo)
            fixed = e.get("fixed", fixed)
            last = e.get("last_affected", last)
        v = _key(version)
        if major_only:
            v = [v[0], 10**9, 10**9]
        if _key(lo) <= v and (fixed is None or v < _key(fixed)) and (last is None or v <= _key(last)):
            return True
    return False


def findings(uses: list[dict], post_json, get_json) -> tuple[list[dict], int]:
    """(findings, actions pinned to a commit): one finding per action, tag and advisory. One OSV batch query names the
    advisories of each action; their ranges are read once each and matched here (OSV's API doesn't match versions in
    this ecosystem)."""
    tagged = sorted({(u["action"], u["ref"]) for u in uses if version_of(u["ref"])})
    pinned = sum(1 for u in uses if SHA.match(u["ref"]))
    actions = sorted({a for a, _ref in tagged})
    if not actions:
        return [], pinned
    got = post_json(OSV_BATCH, {"queries": [{"package": {"ecosystem": "GitHub Actions", "name": a}} for a in actions]})
    ids = {a: [v["id"] for v in (res or {}).get("vulns") or []] for a, res in zip(actions, (got or {}).get("results") or [])}
    details = {i: get_json(f"https://api.osv.dev/v1/vulns/{i}") for i in sorted({i for v in ids.values() for i in v})}
    files = {}
    for u in uses:
        files.setdefault((u["action"], u["ref"]), set()).add(u["file"])
    out = []
    for action, ref in tagged:
        for i in ids.get(action, []):
            doc = details.get(i) or {}
            hit = next((a for a in doc.get("affected") or [] if (a.get("package") or {}).get("name", "").lower() == action.lower()), None)
            if hit and affected(version_of(ref), hit.get("ranges")):
                fixed = next((e["fixed"] for r in hit.get("ranges") or [] for e in r.get("events") or [] if e.get("fixed")), None)
                where = sorted(files.get((action, ref), []))
                out.append({"id": i, "aliases": doc.get("aliases") or [], "ecosystem": "GitHub Actions", "package": action,
                            "version": ref, "file": where[0] if where else None, "files": where,
                            "severity": "unrated", "fixed": fixed, "malware": False, "source": "OSV (GitHub Actions)"})
    return out, pinned
