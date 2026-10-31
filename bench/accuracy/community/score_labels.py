"""Score the labelled first non-author comments: how many issue-metrics counts as a first response were drive-bys, how
many real project answers the roles-only maintainer rule misses, and what the regular-responder rule gets right and
wrong, with Wilson ranges and agreement between two labellings.

    python bench/accuracy/community/score_labels.py --crawl <crawl folder> [--home <work folder> --set main|validation]

With --home, the work folder's labels are frozen into labels-<set>.csv beside this script (links and labels only, no
comment text). The main set chose the regular-responder rule; the validation set is a fresh stratified sample from other
repos, drawn after the rule was fixed (responses.py --exclude --stratify), so its numbers are held out.
"""
import argparse
import csv
import json
import os
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import httpx

sys.path.insert(0, str(Path(__file__).parent))
from responses import _bot, load  # noqa: E402

from stackvitals.core.stats import wilson  # noqa: E402

HERE = Path(__file__).parent
KINDS = ("project_answer", "peer_help", "drive_by")


def _share(k: int, n: int) -> dict:
    lo, hi = wilson(k, n)
    return {"n": n, "share": round(k / n, 4) if n else None, "low": round(lo, 4), "high": round(hi, 4)}


def _kappa(a: list[str], b: list[str]) -> float | None:
    if not a:
        return None
    agree = sum(x == y for x, y in zip(a, b)) / len(a)
    ca, cb = Counter(a), Counter(b)
    chance = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (len(a) ** 2)
    return round((agree - chance) / (1 - chance), 4) if chance < 1 else 1.0


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()] if path.exists() else []


def freeze(home: Path, crawl: Path, name: str) -> Path:
    """Write labels-<name>.csv: one row per item with its link, both labellings and the sampling stratum."""
    items = {r["id"]: r for r in _jsonl(home / "responses-sample.jsonl")}
    labels = {r["id"]: r for p in sorted(home.glob("labels-0*.jsonl")) for r in _jsonl(p)}
    second = {r["id"]: r["kind"] for r in _jsonl(home / "labels-second.jsonl")}
    key = {r["id"]: r["regular"] for r in _jsonl(home / "responses-key.jsonl")}
    missing = sorted(set(items) - set(labels))
    if missing:
        raise SystemExit(f"items without a label: {missing[:20]}")
    names = dict(duckdb.sql(f"""SELECT repo_id, any_value(name) FROM read_parquet('{(crawl / 'repo_meta' / '*.parquet').as_posix()}',
                                union_by_name = true) GROUP BY 1""").fetchall())
    # A few repos have no row in the crawl's repo table: one API call each finds the name.
    headers = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}"} if os.environ.get("GH_TOKEN") else {}
    for repo in {it["repo"] for it in items.values()} - {k for k, v in names.items() if v}:
        resp = httpx.get(f"https://api.github.com/repositories/{repo}", headers=headers, timeout=30)
        if resp.status_code == 200:
            names[repo] = resp.json()["full_name"]
    out = HERE / f"labels-{name}.csv"
    with out.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "repo_id", "issue", "url", "stratum", "kind", "confidence", "second_kind"])
        for i in sorted(items):
            it, lab = items[i], labels[i]
            stratum = ("regular" if key[i] else "other") if i in key else ""
            w.writerow([i, it["repo"], it["issue"], f"https://github.com/{names.get(it['repo'], '')}/issues/{it['issue']}",
                        stratum, lab["kind"], lab.get("confidence", ""), second.get(i, "")])
    return out


def _regular_flags(rows: list[dict], crawl: Path) -> list[bool]:
    """Whether each item's first non-author comment came from a regular responder, recomputed from the crawl."""
    issues, comments, _mergers, regulars = load(crawl)
    authors = {(r, n): (a, c) for r, n, a, _as, c, _cl, _f, _t in issues}
    flags = []
    for row in rows:
        repo, number = int(row["repo_id"]), int(row["issue"])
        author, created = authors[(repo, number)]
        first = next((c for c in sorted((c for c in comments[(repo, number)] if c["at"] and c["at"] >= created), key=lambda c: c["at"])
                      if c["login"] != author and not _bot(c)), None)
        flags.append(bool(first) and first["login"] in regulars.get(repo, set()))
    return flags


def _rule(rows: list[dict], flags: list[bool], weights: dict | None = None, seed: int = 13) -> dict:
    """What the regular-responder rule counts: drive-bys among them, and the share of all project answers it catches
    (weighted by stratum when the sample was stratified, with a bootstrap range)."""
    sure = [(r, f) for r, f in zip(rows, flags) if r["kind"] != "unclear"]
    counted = [r for r, f in sure if f]
    out = {"counted": len(counted),
           "drive_by_among_counted": _share(sum(r["kind"] == "drive_by" for r in counted), len(counted)),
           "real_answer_among_counted": _share(sum(r["kind"] != "drive_by" for r in counted), len(counted))}

    def caught(sample):
        w = (lambda r: weights[r["stratum"]]) if weights else (lambda r: 1.0)
        pa = [(r, f) for r, f in sample if r["kind"] == "project_answer"]
        total = sum(w(r) for r, _ in pa)
        return sum(w(r) for r, f in pa if f) / total if total else None
    est = caught(sure)
    rng = random.Random(seed)
    strata = {}
    for r, f in sure:
        strata.setdefault(r.get("stratum") if weights else "", []).append((r, f))
    boot = sorted(x for x in (caught([rng.choice(g) for g in strata.values() for _ in g]) for _ in range(2000)) if x is not None)
    out["project_answers_caught"] = {"n": sum(r["kind"] == "project_answer" for r, _ in sure),
                                     "share": round(est, 4) if est is not None else None,
                                     "low": round(boot[int(0.025 * len(boot))], 4) if boot else None,
                                     "high": round(boot[int(0.975 * len(boot)) - 1], 4) if boot else None}
    return out


def _weighted(sure: list[dict], weights: dict, kind: str, seed: int = 13) -> dict:
    """The pool's share of one kind from a stratified sample: each stratum weighted by its pool size, bootstrap range."""
    def share(rows):
        total = sum(weights[r["stratum"]] for r in rows)
        return sum(weights[r["stratum"]] for r in rows if r["kind"] == kind) / total
    rng = random.Random(seed)
    strata = {}
    for r in sure:
        strata.setdefault(r["stratum"], []).append(r)
    boot = sorted(share([rng.choice(g) for g in strata.values() for _ in g]) for _ in range(2000))
    return {"n": len(sure), "share": round(share(sure), 4), "low": round(boot[50], 4), "high": round(boot[1949], 4)}


def score(path: Path, crawl: Path, pool: dict | None = None) -> dict:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    flags = _regular_flags(rows, crawl)
    sure = [r for r in rows if r["kind"] != "unclear"]
    out = {"items": len(rows), "kinds": dict(Counter(r["kind"] for r in rows).most_common())}
    weights = None
    if pool and all(r["stratum"] for r in rows):
        drawn = Counter(r["stratum"] for r in rows)
        weights = {s: pool[s] / drawn[s] for s in drawn}
        out["strata"] = {s: {"drawn": drawn[s], "pool": pool[s]} for s in drawn}
        # Shares of the whole pool of non-maintainer first comments, as in the main set.
        out |= {"drive_by_counted_by_issue_metrics": _weighted(sure, weights, "drive_by"),
                "project_answers_missed_by_roles_only": _weighted(sure, weights, "project_answer"),
                "peer_help": _weighted(sure, weights, "peer_help")}
    else:
        # Unstratified: every share is a plain share of the sample.
        out |= {"drive_by_counted_by_issue_metrics": _share(sum(r["kind"] == "drive_by" for r in sure), len(sure)),
                "project_answers_missed_by_roles_only": _share(sum(r["kind"] == "project_answer" for r in sure), len(sure)),
                "peer_help": _share(sum(r["kind"] == "peer_help" for r in sure), len(sure))}
    out["regular_responders"] = _rule(rows, flags, weights)
    pairs = [(r["kind"], r["second_kind"]) for r in rows if r["second_kind"]]
    if pairs:
        out["agreement"] = {"items": len(pairs), "same": round(sum(a == b for a, b in pairs) / len(pairs), 4),
                            "kappa": _kappa([a for a, _ in pairs], [b for _, b in pairs])}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--crawl", type=Path, required=True, help="the crawl folder the samples were drawn from")
    ap.add_argument("--home", type=Path, default=None, help="work folder whose labels are frozen into labels-<set>.csv")
    ap.add_argument("--set", default="main", choices=("main", "validation"))
    ap.add_argument("--labeller", default="model (Claude), audit pending")
    args = ap.parse_args(argv)
    if args.home:
        freeze(args.home, args.crawl, args.set)
    out = {"labeller": args.labeller, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    for name in ("main", "validation"):
        path = HERE / f"labels-{name}.csv"
        if path.exists():
            results = HERE / f"responses-{name}-results.json"
            pool = json.loads(results.read_text(encoding="utf-8")).get("pool") if results.exists() else None
            out[name] = score(path, args.crawl, pool)
    (HERE / "labels-results.json").write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
