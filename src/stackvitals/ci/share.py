"""Opt-in shared benchmarks ([benchmarks] share = true): this repo's CI figures, rounded and without its name unless
allowed, as a prefilled issue on StackVitals' public repo. Nothing is sent by the Action: a person opens the link and
files the issue. Once 10+ repos of a kind have shared, their peer group is published beside the public one."""
import json
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from mergescout.bench.ci import tier
from stackvitals.ci.bench import BENCH_REPO, PUBLIC_HOME

KIND, SCHEMA, MIN_PUSHES = "ci-benchmark", 1, 20
FIELDS = ("schema", "kind", "id", "month", "language", "tier", "pushes", "median_s", "p90_s", "first_try_share",
          "fail_share", "rerun_share")
ID_FILE = "ci/share-id"  # in the data branch


def share_id(root: Path) -> str:
    """A random id kept in the data branch, so a later month replaces this repo's figures; it says nothing about the repo."""
    path = Path(root) / ID_FILE
    try:
        found = path.read_text(encoding="utf-8").strip()
    except OSError:
        found = ""
    if len(found) == 16 and all(c in "0123456789abcdef" for c in found):
        return found
    path.parent.mkdir(parents=True, exist_ok=True)
    found = secrets.token_hex(8)
    path.write_text(found + "\n", encoding="utf-8")
    return found


def figures(stats: dict | None, language: str | None, stars: int | None, sid: str, now: datetime,
            name: str | None = None) -> dict | None:
    """The shared figures, or None with too few pushes to share safely."""
    if not stats or stats.get("pushes", 0) < MIN_PUSHES:
        return None
    doc = {"schema": SCHEMA, "kind": KIND, "id": sid, "month": f"{now:%Y-%m}", "language": language or "other",
           "tier": tier(stars), "pushes": int(round(stats["pushes"], -1)), "median_s": int(round(stats["median_s"] / 30) * 30),
           "p90_s": int(round(stats["p90_s"] / 60) * 60), "first_try_share": round(stats["first_try_share"], 2),
           "fail_share": round(stats["fail_share"], 2), "rerun_share": round(stats["rerun_share"], 2)}
    return {**doc, "repo": name} if name else doc


def link(doc: dict) -> str:
    # The issue form adds the "benchmark" label for anyone; a plain new-issue link drops labels for people without triage rights.
    title = f"Benchmark figures: {doc['language']}, {doc['tier']} stars, {doc['month']}"
    # Figures are filed on the public home once there is one; the daily collector reads both repos.
    return f"https://github.com/{PUBLIC_HOME or BENCH_REPO}/issues/new?" + urlencode(
        {"template": "benchmark.yml", "title": title, "figures": json.dumps(doc, indent=1)})


def summary_line(doc: dict | None) -> str:
    if not doc:
        return f"Shared benchmarks are on, but this repo had fewer than {MIN_PUSHES} pushes in the window; nothing to share yet."
    who = f"named {doc['repo']}" if doc.get("repo") else "without the repo's name"
    return (f"Shared benchmarks: [file this month's rounded CI figures]({link(doc)}) ({who}; the issue shows the account "
            "that files it). Peer groups are published once 10+ repos of a kind have shared.")
