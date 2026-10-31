"""How much the labels move each headline number: every card scored three ways, on Claude's labels, on Gemini's labels
and on the adjudicated labels, by the card's own scripts run on a private copy (the published files are untouched).

    python bench/accuracy/sensitivity.py --work bench/accuracy/.work

Writes bench/accuracy/label-sensitivity.json.
"""
import argparse
import csv
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def _gemini(path: Path) -> dict:
    return {r["id"]: r for r in csv.DictReader(path.open(encoding="utf-8"))}


def _sandbox(work: Path, name: str, folder: str) -> Path:
    """A copy of one card's scripts (and fair.py) whose outputs land in the copy."""
    root = work / "sens" / name
    if root.exists():
        shutil.rmtree(root)
    (root / folder).mkdir(parents=True)
    # Scripts and every data file beside them (a scorer may read its sampling pool from one).
    for p in (HERE / folder).iterdir():
        if p.is_file():
            shutil.copy(p, root / folder / p.name)
    shutil.copy(HERE / "fair.py", root / "fair.py")
    return root


def _run(script: Path, *args: str) -> None:
    subprocess.run([sys.executable, str(script), *args], check=True, capture_output=True, text=True)


def flaky(work: Path, which: str) -> dict:
    home = work / ("flaky-final" if which == "adjudicated" else "flaky")
    if which == "gemini":
        g, gm = _gemini(HERE / "flaky/labels-gemini-flaky.csv"), _gemini(HERE / "flaky/labels-gemini-masking.csv")
        home = work / "sens" / "flaky-gemini-home"
        if home.exists():
            shutil.rmtree(home)
        shutil.copytree(work / "flaky", home, ignore=shutil.ignore_patterns("gemini-cache", "adjudicate-*", "old-labels"))
        fields = ("cause", "caused_by_change", "own_failure")
        _write_jsonl(home / "labels.jsonl", [{**r, **{k: g[str(r["id"])][k] for k in fields}}
                                             for r in _jsonl(work / "flaky" / "labels.jsonl")])
        _write_jsonl(home / "asof-labels.jsonl", [{**r, **{k: gm[str(r["id"])][k] for k in fields}}
                                                  for r in _jsonl(work / "flaky" / "asof-labels.jsonl")])
    root = _sandbox(work, f"flaky-{which}", "flaky")
    _run(root / "flaky/score.py", "--home", str(home), "--log", str(home / "sampler-log.txt"))
    _run(root / "flaky/masking.py", "score", "--home", str(home))
    card = json.loads((root / "flaky/card.json").read_text(encoding="utf-8"))
    mask = json.loads((root / "flaky/masking-results.json").read_text(encoding="utf-8"))
    return {"event_precision": card["event_precision"]["share"], "event_precision_n": card["event_precision"]["n"],
            "plain_retry_precision": card["plain_retry_rule"]["precision"], "miss_rate": card["miss_rate"]["share"],
            "masking_old_rule": mask["old_rule"]["share"],
            "masking_new_rule": f"{mask['new_rule']['caused_by_change']} of {mask['new_rule']['n']}"}


def dora(work: Path, which: str, name: str = "dora-sources") -> dict:
    home = work / (f"{name}-final" if which == "adjudicated" else name)
    if which == "gemini":
        cache_rows = {}
        for p in (work / name / "gemini-cache").rglob("*.json"):
            r = json.loads(p.read_text(encoding="utf-8"))
            cache_rows[r["id"]] = r
        home = work / "sens" / f"{name}-gemini-home"
        if home.exists():
            shutil.rmtree(home)
        shutil.copytree(work / name, home, ignore=shutil.ignore_patterns("gemini-cache", "adjudicate-*", "labels-*.jsonl"))
        rows = []
        for r in (r for f in sorted((work / name).glob("labels-[0-9].jsonl")) for r in _jsonl(f)):
            got = cache_rows.get(r["repo"], {})
            ships = {w["path"]: w["ships"] for w in got.get("workflows") or []}
            rows.append({**r, "sources": got.get("sources") or r["sources"],
                         "workflows": {p: ships.get(p) for p in r["workflows"]}})
        _write_jsonl(home / "labels-0.jsonl", rows)
    root = _sandbox(work, f"{name}-{which}", "dora")
    _run(root / "dora/sources.py", "score", "--home", str(home))
    out = json.loads((root / "dora/sources-results.json").read_text(encoding="utf-8"))
    return {k: out["source_right"][k]["share"] for k in ("stackvitals", "devlake", "merges")} | {
        "workflow_precision": out["workflow_rule"]["stackvitals"]["precision"]["share"],
        "workflow_recall": out["workflow_rule"]["stackvitals"]["recall"]["share"]}


def community(work: Path, which: str) -> dict:
    root = _sandbox(work, f"community-{which}", "community")
    column = {"claude": "claude_kind", "gemini": "gemini_kind", "adjudicated": "kind"}[which]
    for name in ("labels-main.csv", "labels-validation.csv"):
        path = root / "community" / name
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        for r in rows:
            r["kind"] = r[column] or r["kind"]
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    _run(root / "community/score_labels.py", "--crawl", str(work / "crawl"))
    v = json.loads((root / "community/labels-results.json").read_text(encoding="utf-8"))["validation"]
    return {"drive_bys_counted_by_issue_metrics": v["drive_by_counted_by_issue_metrics"]["share"],
            "project_answers_missed_by_roles_only": v["project_answers_missed_by_roles_only"]["share"],
            "regular_responders_catch": v["regular_responders"]["project_answers_caught"]["share"],
            "drive_bys_among_what_they_add": v["regular_responders"]["drive_by_among_counted"]["share"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--cards", nargs="*", default=["flaky", "dora", "community", "dora-more"])
    args = ap.parse_args(argv)
    path = HERE / "label-sensitivity.json"
    out = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    more = lambda work, which: dora(work, which, "dora-sources-more")  # noqa: E731
    for name, fn in (("flaky", flaky), ("dora", dora), ("community", community), ("dora-more", more)):
        if name not in args.cards:
            continue
        out[name] = {which: fn(args.work, which) for which in ("claude", "gemini", "adjudicated")}
        print(name, json.dumps(out[name]))
    out["note"] = ("Each number scored on Claude's labels, Gemini's labels and the adjudicated labels; adjudication was "
                   "done by Claude, blind to which labeller said what. See adjudicator-crosscheck.json.")
    (HERE / "label-sensitivity.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
