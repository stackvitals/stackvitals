"""Code survival: of the lines a squash-merged pull request added, how many are still in the default branch 30 and 90
days later (git blame, read through GitHub's API), split by people's and agents' PRs. DevLake shows line age per file;
this asks the question teams adopting agents have: does agent code last?"""
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from mergescout.github.graphql import GraphQLError

AGES = (30, 90)
PER_RUN = 12
FILES = 8
FILE = "survival.json"
HEX = re.compile(r"[0-9a-f]{40}")


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def due(prs: list[dict], saved: dict, now: datetime, per_run: int = PER_RUN) -> list[tuple[dict, int]]:
    """(PR, age) still to measure: merged at least `age` days ago (but within 30 days past it), newest first."""
    out = []
    for p in sorted((p for p in prs if p.get("mg") and HEX.fullmatch(p.get("mc") or "") and p.get("add")), key=lambda p: p["mg"], reverse=True):
        days = (now - _t(p["mg"])).days
        for age in AGES:
            if age <= days < age + 30 and str(age) not in (saved.get(str(p["n"])) or {}):
                out.append((p, age))
    return out[:per_run]


def _query(mc: str, paths: list[str]) -> str:
    parts = " ".join(f'f{i}: blame(path: {json.dumps(path)}) {{ ranges {{ startingLine endingLine commit {{ oid }} }} }}'
                     for i, path in enumerate(paths))
    return ("query($owner:String!,$name:String!) { rateLimit { cost remaining resetAt } repository(owner:$owner,name:$name) { "
            f'm: object(oid:"{mc}") {{ ... on Commit {{ parents {{ totalCount }} }} }} '
            f'h: defaultBranchRef {{ target {{ ... on Commit {{ {parts} }} }} }} }} }}')


def measure_one(gql, owner: str, name: str, p: dict) -> dict | None:
    """{"kept": lines still blamed on its merge commit, "added": lines it added}; None when it wasn't squash-merged
    (its lines belong to other commits then) or the API refused."""
    paths = [x for x in (p.get("paths") or [])][:FILES]
    if not paths:
        return None
    try:
        repo = gql.query(_query(p["mc"], paths), {"owner": owner, "name": name}).data["repository"]
    except GraphQLError:
        return None
    if ((repo.get("m") or {}).get("parents") or {}).get("totalCount") != 1:
        return None
    target = ((repo.get("h") or {}).get("target")) or {}
    kept = sum(r["endingLine"] - r["startingLine"] + 1 for i in range(len(paths))
               for r in ((target.get(f"f{i}") or {}).get("ranges") or []) if (r.get("commit") or {}).get("oid") == p["mc"])
    return {"kept": kept, "added": p["add"], "files": len(paths), "all_files": len(p.get("paths") or []) <= FILES}


def collect(gql, store_dir: Path, owner: str, name: str, prs: list[dict], now: datetime) -> dict:
    """Measures the PRs due this run and keeps every answer: {pr: {"30": {...}, "90": {...}}}."""
    path = Path(store_dir) / FILE
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    for p, age in due(prs, saved, now):
        got = measure_one(gql, owner, name, p)
        saved.setdefault(str(p["n"]), {})[str(age)] = got or {"skipped": True}
    path.write_text(json.dumps(saved, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    return saved


def summary(saved: dict, prs: list[dict], kind_of) -> dict | None:
    """Share of added lines still there at each age, for people's PRs and agents' PRs (kind_of(pr) -> "agent" or other)."""
    by_n = {str(p["n"]): p for p in prs}
    out = {}
    for age in AGES:
        for who in ("people", "agents"):
            rows = [v[str(age)] for n, v in saved.items() if str(age) in v and not v[str(age)].get("skipped") and n in by_n
                    and v[str(age)].get("all_files") and (kind_of(by_n[n]) == "agent") == (who == "agents")]
            added = sum(r["added"] for r in rows)
            if rows and added:
                out.setdefault(str(age), {})[who] = {"prs": len(rows), "share": round(min(1.0, sum(r["kept"] for r in rows) / added), 4)}
    return out or None
