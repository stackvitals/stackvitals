"""One command per headline: re-run the scorer behind a published result file and check it gives the same numbers.

    python bench/accuracy/reproduce.py list                 # every result file, its command and what it needs
    python bench/accuracy/reproduce.py check heldout        # re-score one card and compare (clock fields ignored)
    python bench/accuracy/reproduce.py check --all          # every card whose inputs are here
    python bench/accuracy/reproduce.py pack --out data.tar.gz   # the scorers' inputs in one archive (shared on request)

Scoring reads the work folders (.work/, the evidence each card was labelled from), never the network, except where a
card says "network". Scorers rewrite committed files, so every committed file under bench/accuracy and docs/ is put
back after each check. The labels themselves are committed beside each card (ids, links and labels; no logs or text).
"""
import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
W = ".work"  # relative to bench/accuracy
LABELLER = '--labeller "Claude and Gemini 3.5 Flash-Lite; disagreements adjudicated blind by Claude; no person audited"'
sys.path.insert(0, str(ROOT / "src"))
from stackvitals.core.store import _steady  # noqa: E402

# name -> (result file, command run from bench/accuracy, inputs under bench/accuracy, network?)
CARDS = {
    "nulls": ("uncertainty/nulls-results.json", f"uncertainty/nulls.py {W}/flow --points 12 --shuffles 20 --seed 13", [f"{W}/flow"], False),
    "nulls2": ("uncertainty/nulls-2week-results.json", f"uncertainty/nulls.py {W}/flow --points 12 --shuffles 20 --seed 13 --slow-weeks 2 --out uncertainty/nulls-2week-results.json", [f"{W}/flow"], False),
    "shrink": ("uncertainty/shrinkage-results.json", f"uncertainty/shrinkage.py {W}/crawlci --draws 20 --seed 13", [f"{W}/crawlci"], False),
    "ai": ("ai/replicate-results.json", f"ai/replicate.py {W}/crawl/prs --placebos 200 --seed 13", [f"{W}/crawl/prs"], False),
    "flaky": ("flaky/card.json", f"flaky/score.py --home {W}/flaky-final --log {W}/flaky-final/sampler-log.txt --second {W}/flaky-final/second.jsonl {LABELLER}", [f"{W}/flaky-final"], False),
    "masking": ("flaky/masking-results.json", f"flaky/masking.py score --home {W}/flaky-final", [f"{W}/flaky-final"], False),
    "sources": ("dora/sources-results.json", f"dora/sources.py score --home {W}/dora-sources-final {LABELLER}", [f"{W}/dora-sources-final"], False),
    "linkage": ("dora/linkage-results.json", f"dora/linkage.py {W}/flow --check", [f"{W}/flow"], True),
    "spread": ("dora/spread-results.json", f"dora/spread.py {W}/crawl", [f"{W}/crawl/prs", f"{W}/crawl/repo_meta"], False),
    "labels": ("community/labels-results.json", f"community/score_labels.py --crawl {W}/crawl {LABELLER}", [f"{W}/crawl"], False),
    "responses": ("community/responses-results.json", f"community/responses.py {W}/crawl --home {W}/community-main", [f"{W}/crawl", f"{W}/community-main"], False),
    "agents": ("agents/results.json", f"agents/score.py --out {W}/agents", [f"{W}/agents"], False),
    "linkage_more": ("dora/linkage-more-results.json", f"dora/linkage.py {W}/flow-more/flow --out dora/linkage-more-results.json --check", [f"{W}/flow-more"], True),
    "sens": ("label-sensitivity.json", f"sensitivity.py --work {W}", [f"{W}/flaky", f"{W}/dora-sources", f"{W}/crawl", f"{W}/sens"], False),
    "cross": ("adjudicator-crosscheck.json", f"crosscheck.py --work {W} --run", [f"{W}/crosscheck-cache"], False),
    "ag_flaky": ("flaky/agreement-gemini-flaky.json", f"labeller.py flaky --work {W}/flaky --compare", [f"{W}/flaky"], False),
    "ag_main": ("community/agreement-gemini-main.json", f"labeller.py community-main --work {W}/community-main --compare", [f"{W}/community-main"], False),
    "ag_val": ("community/agreement-gemini-validation.json", f"labeller.py community-validation --work {W}/community-validation --compare", [f"{W}/community-validation"], False),
    "ag_dora": ("dora/agreement-gemini-sources.json", f"labeller.py dora-sources --work {W}/dora-sources --compare", [f"{W}/dora-sources"], False),
    "ag_dora_more": ("dora/agreement-gemini-sources-more.json", f"labeller.py dora-sources-more --work {W}/dora-sources-more --compare", [f"{W}/dora-sources-more"], False),
    "dl_cfg": ("dora/devlake-configured-results.json", f"dora/devlake_configured.py --home {W}/dora-sources-final", [f"{W}/dora-sources-final"], True),
    "sources_more": ("dora/sources-more-results.json", f"dora/sources.py score --home {W}/dora-sources-more-final --suffix=-more {LABELLER}", [f"{W}/dora-sources-more-final"], False),
    "dl_cfg_more": ("dora/devlake-configured-more-results.json", f"dora/devlake_configured.py --home {W}/dora-sources-more-final --suffix=-more", [f"{W}/dora-sources-more-final"], True),
    "natural": ("flaky/natural-results.json", f"flaky/natural.py --home {W}/flaky --final {W}/flaky-final", [f"{W}/flaky", f"{W}/flaky-final"], False),
    "already": ("flaky/already-results.json", f"flaky/already.py --home {W}/flaky --final {W}/flaky-final", [f"{W}/flaky", f"{W}/flaky-final"], False),
    "maybe": ("flaky/maybe-results.json", f"flaky/maybe.py --home {W}/flaky-final", [f"{W}/flaky-final"], False),
    "outside": ("flaky/outside-results.json", f"flaky/outside.py --home {W}/flaky-final", [f"{W}/flaky-final"], False),
    "triage": ("agents/triage-results.json", f"agents/triage_check.py --out {W}/agents --flaky-home {W}/flaky", [f"{W}/agents", f"{W}/flaky"], False),
    "heldout": ("flaky/heldout-results.json", f"flaky/heldout.py score --home {W}/wide --final {W}/final/heldout.jsonl", [f"{W}/wide", f"{W}/final"], False),
    "agents2": ("agents/results2.json", f"agents/score2.py --out {W}/agents2 --flaky-home {W}/flaky --flaky-final {W}/flaky-final "
                f"--wide {W}/wide --wide-final {W}/final/heldout.jsonl --triage", [f"{W}/agents2", f"{W}/flaky", f"{W}/wide"], False),
    "pr_details": ("flaky/pr-details-results.json", f"flaky/pr_details.py --flaky-home {W}/flaky --flaky-final {W}/flaky-final "
                   f"--wide {W}/wide --wide-final {W}/final/heldout.jsonl --cache {W}/pr-checks.json", [f"{W}/flaky", f"{W}/wide", f"{W}/pr-checks.json"], False),
    "ai_detect": ("ai/detection-results.json", f"ai/detection.py score --home {W}/aidetect --final {W}/final/ai-detection.jsonl", [f"{W}/aidetect", f"{W}/final"], False),
    "ai_adopt": ("ai/adoption-results.json", f"ai/adoption.py {W}/crawl/prs --draws 400 --seed 23", [f"{W}/crawl/prs"], False),
    "triage_rule": ("community/triage-results.json", f"community/triage.py score --crawl {W}/crawl --home {W}/triage", [f"{W}/crawl", f"{W}/triage"], False),
    "incidents": ("dora/incidents-results.json", f"dora/incidents.py score --home {W}/incidents --final {W}/final/dora-incidents.jsonl", [f"{W}/incidents", f"{W}/final"], False),
    "deps_incidents": ("deps/incidents-results.json", "deps/incidents.py", [], True),
    "replay": ("replay/replay-results.json", f"replay/replay.py score --home {W}/replay --labels {W}/final/replay.jsonl", [f"{W}/replay", f"{W}/final"], False),
}


# Scorers that read cached answers and call the network only on a cache miss.
CACHED = {"pr_details", "cross", "triage", "agents2"}


def _tracked() -> list[Path]:
    out = subprocess.run(["git", "--git-dir", str(ROOT / ".git"), "--work-tree", str(ROOT), "ls-files", "bench/accuracy", "docs"],
                         capture_output=True, text=True, check=True).stdout.split()
    return [ROOT / p for p in out]


def _diff(a, b, path: str = "") -> list[str]:
    """Where two results differ, as "path: published -> re-run"."""
    if isinstance(a, dict) and isinstance(b, dict):
        return [d for k in sorted(set(a) | set(b), key=str) for d in _diff(a.get(k), b.get(k), f"{path}.{k}")]
    if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
        return [d for i, (x, y) in enumerate(zip(a, b)) for d in _diff(x, y, f"{path}[{i}]")]
    return [] if a == b else [f"{path}: {str(a)[:60]} -> {str(b)[:60]}"]


def check(name: str) -> str:
    result, cmd, needs, network = CARDS[name]
    missing = [p for p in needs if not (HERE / p).exists()]
    if missing:
        return f"needs {', '.join(missing)} (the evidence archive from `reproduce.py pack`, shared on request)"
    if network:
        return "reads live GitHub data, so a re-run today differs; run it by hand with GH_TOKEN set"
    target = HERE / result
    if not target.exists():
        return "no published result yet"
    published = target.read_text(encoding="utf-8")
    before = json.loads(published)
    keep = tempfile.mkdtemp(prefix="reproduce-")
    files = _tracked()
    for f in files:
        dest = Path(keep) / f.relative_to(ROOT)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dest)
    note = " (offline while its cache holds every answer; a miss calls GitHub or Gemini)" if name in CACHED else ""
    try:
        # Gone before the run, so a scorer that writes nothing can't pass by leaving the published file in place.
        target.unlink()
        run = subprocess.run([sys.executable, *shlex.split(cmd)], cwd=HERE, capture_output=True, text=True, timeout=3600)
        if run.returncode:
            return f"the scorer failed: {(run.stderr or run.stdout).strip().splitlines()[-1:]}"
        if not target.exists():
            return f"the scorer failed: it didn't write {result}"
        after = json.loads(target.read_text(encoding="utf-8"))
        if _steady(after) == _steady(before):
            return "same numbers" + note
        return "DIFFERENT numbers: " + "; ".join(_diff(_steady(before), _steady(after))[:3])
    finally:
        for f in files:
            shutil.copy2(Path(keep) / f.relative_to(ROOT), f)
        target.write_text(published, encoding="utf-8")
        shutil.rmtree(keep, ignore_errors=True)


def pack(out: Path) -> None:
    paths = sorted({p for _r, _c, needs, _n in CARDS.values() for p in needs if (HERE / p).exists()})
    with tarfile.open(out, "w:gz") as tar:
        for p in paths:
            tar.add(HERE / p, arcname=f"bench/accuracy/{p}")
    print(f"{out}: {len(paths)} folders, {out.stat().st_size / 1e6:.0f} MB")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    c = sub.add_parser("check")
    c.add_argument("names", nargs="*")
    c.add_argument("--all", action="store_true")
    p = sub.add_parser("pack")
    p.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "list":
        for name, (result, cmd, needs, network) in CARDS.items():
            print(f"{name:13} {result:45} python bench/accuracy/{cmd}" + ("   [network]" if network else ""))
        return 0
    if args.cmd == "pack":
        pack(args.out)
        return 0
    names = list(CARDS) if args.all else args.names
    bad = 0
    for name in names:
        said = check(name)
        bad += said.startswith("DIFFERENT") or said.startswith("the scorer failed")
        print(f"{name:13} {said}", flush=True)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
