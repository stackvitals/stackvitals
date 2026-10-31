"""How big the data branch gets: a busy repo's CI history written the way the Action writes it (records appended to
today's file, one commit per run, past days compressed, days past retention removed), for hundreds of days, with and
without the opt-in squash, measured after `git gc` at checkpoints.

    python bench/accuracy/features/branch_growth.py <one real CI day file> --out <folder> [--days 400] [--runs 24]
        [--scale 1.0] [--squash-every 1000] [--retention 180]

Every simulated day replays the real day's records with the date moved, so sizes and compression are realistic.
"""
import argparse
import json
import os
import random
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from stackvitals.ci.store import DataStore  # noqa: E402

BRANCH = "stackvitals-data"


def _git(repo: Path, *args: str) -> str:
    # Pinned to the simulation's own .git: if that folder vanishes, git fails instead of finding the real repo above.
    pin = [] if args[:1] == ("init",) else [f"--git-dir={repo / '.git'}", f"--work-tree={repo}"]
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(Path(repo).resolve().parent)}
    return subprocess.run(["git", *pin, *args], cwd=repo, check=True, capture_output=True, text=True, env=env).stdout


def _size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def history_mb(repo: Path) -> float:
    """What a clone downloads for the branch: git's own packed plus loose object size (KiB) after a full repack."""
    _git(repo, "repack", "-a", "-d", "-q")
    stats = dict(line.split(": ", 1) for line in _git(repo, "count-objects", "-v").splitlines() if ": " in line)
    return round((int(stats.get("size-pack", 0)) + int(stats.get("size", 0))) * 1024 / 1e6, 2)


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--allow-empty", "-m", message)


def squash(repo: Path, message: str) -> None:
    """The Action's squash: the same files as one new root commit, the old history dropped."""
    _git(repo, "checkout", "-q", "--orphan", "stackvitals-squash")
    _commit(repo, message)
    _git(repo, "branch", "-D", BRANCH)
    _git(repo, "branch", "-m", BRANCH)
    _git(repo, "reflog", "expire", "--expire=now", "--all")
    _git(repo, "gc", "-q", "--prune=now")


def simulate(day_file: Path, out: Path, days: int = 400, runs: int = 24, retention: int = 180,
             squash_every: int | None = None, scale: float = 1.0, checkpoint: int = 50, seed: int = 13) -> dict:
    lines = [x for x in day_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    if scale < 1:
        lines = random.Random(seed).sample(lines, max(1, int(len(lines) * scale)))
    template_day = json.loads(lines[0]).get("cr", "")[:10]
    repo = out / "repo"
    repo.mkdir(parents=True, exist_ok=False)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "sim")
    _git(repo, "config", "user.email", "sim@example.invalid")
    _git(repo, "config", "core.autocrlf", "false")
    _git(repo, "config", "gc.auto", "0")
    _git(repo, "checkout", "-q", "--orphan", BRANCH)
    store = DataStore(repo)
    start, commits, total, squashes, points = date(2025, 1, 1), 0, 0, 0, []
    began = time.time()
    per_run = max(1, -(-len(lines) // runs))
    for d in range(days):
        day = (start + timedelta(days=d)).isoformat()
        store.compact(day, retention)
        moved = [x.replace(template_day, day)[:-1] + f',"s":{d}}}' for x in lines]
        for k in range(0, len(moved), per_run):
            with (store.days / f"{day}.ndjson").open("a", encoding="utf-8", newline="\n") as f:
                f.write("\n".join(moved[k:k + per_run]) + "\n")
            _commit(repo, f"stackvitals: ci {day} run {k // per_run}")
            commits += 1
            total += 1
            if squash_every and commits >= squash_every:
                squash(repo, f"stackvitals: history squashed {day}")
                commits, squashes = 1, squashes + 1
        if (d + 1) % checkpoint == 0 or d == days - 1:
            points.append({"day": d + 1, "commits_on_branch": commits, "commits_made": total, "squashes": squashes,
                           "git_mb": history_mb(repo),
                           "tree_mb": round(_size(store.days) / 1e6, 2), "seconds": round(time.time() - began)})
            print(json.dumps(points[-1]), flush=True)
    return {"records_per_day": len(lines), "runs_per_day": runs, "days": days, "retention_days": retention,
            "squash_every": squash_every, "checkpoints": points}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("day_file", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--days", type=int, default=400)
    ap.add_argument("--runs", type=int, default=24)
    ap.add_argument("--retention", type=int, default=180)
    ap.add_argument("--squash-every", type=int, default=None)
    ap.add_argument("--scale", type=float, default=1.0)
    ap.add_argument("--checkpoint", type=int, default=50)
    args = ap.parse_args(argv)
    result = simulate(args.day_file, args.out, args.days, args.runs, args.retention, args.squash_every, args.scale,
                      args.checkpoint)
    (args.out / "result.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
