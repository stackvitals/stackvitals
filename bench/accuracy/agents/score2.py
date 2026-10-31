"""Score the bigger head-to-head (prepare2.py): each agent arm's answers, StackVitals alone, and StackVitals with the
opt-in model triage (Gemini, free tier, only for the failures its rules leave undecided), against the labels; GitHub
calls per question for each agent arm; paired tests between arms on the same questions.

    python bench/accuracy/agents/score2.py --out <head-to-head folder> --flaky-home ... --flaky-final ... --wide ...
                                           --wide-final ... [--triage]

Writes results2.json beside this script (counts only).
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))
from fair import by_repo, mcnemar  # noqa: E402
from prepare2 import ARMS, pool  # noqa: E402

from stackvitals.core.stats import wilson  # noqa: E402

SAID = {"known flaky": "flake", "outside failure": "flake", "already failing": "flake", "maybe flaky": "flake",
        "PR details": "flake", "new": "change"}
TRIAGE = {"yes": "change", "no": "flake"}


def _tally(results: dict) -> dict:
    right = sum(v == "right" for v in results.values())
    lo, hi = wilson(right, len(results))
    return {"items": len(results), "right": right, "wrong": sum(v == "wrong" for v in results.values()),
            "unclear": sum(v == "unclear" for v in results.values()), "low": round(lo, 4), "high": round(hi, 4)}


def _grade(said: str, want: str) -> str:
    return "right" if said == want else "unclear" if said not in ("change", "flake") else "wrong"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for name in ("--out", "--flaky-home", "--flaky-final", "--wide", "--wide-final"):
        ap.add_argument(name, type=Path, required=True)
    ap.add_argument("--triage", action="store_true", help="ask Gemini about the undecided failures (cached)")
    args = ap.parse_args(argv)
    out = args.out
    truth = json.loads((out / "truth.json").read_text(encoding="utf-8"))
    want = {(t["k"], t["q"]): "change" if t["caused_by_change"] == "yes" else "flake" for t in truth}
    repo_of = {(t["k"], t["q"]): t["repo"] for t in truth}
    arms = {}
    for arm in ARMS:
        got = {}
        for k in {t["k"] for t in truth}:
            path = out / f"answers-{arm}-{k}.json"
            if path.exists():
                for a in json.loads(path.read_text(encoding="utf-8")).get("items") or []:
                    got[(k, a["q"])] = a.get("answer")
        if got:
            calls = out / f"calls-{arm}.log"
            n = len(calls.read_text(encoding="utf-8").splitlines()) if calls.exists() else 0
            graded = {key: _grade(got.get(key, "unclear"), w) for key, w in want.items() if key in got or
                      any(kk[0] == key[0] for kk in got)}
            arms[arm] = {**_tally(graded), "github_calls": n, "calls_per_item": round(n / len(graded), 1) if graded else None,
                         "_graded": graded}
    alone, triaged, cache_path = {}, {}, out / "triage-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    by_url = {p["url"]: p for p in pool(args)} if args.triage else {}
    for t in truth:
        key = (t["k"], t["q"])
        ans = json.loads((out / f"sv-{t['k']}" / f"ci_failure-{t['q']}.json").read_text(encoding="utf-8"))
        q = next(x for x in json.loads((out / f"questions-{t['k']}.json").read_text(encoding="utf-8"))["items"] if x["q"] == t["q"])
        item = next((f for f in ans["failures"] if f["name"].endswith(q["job"])), {"verdict": "new", "detail": ""})
        alone[key] = _grade(SAID.get(item["verdict"], "unclear"), want[key])
        said = SAID.get(item["verdict"], "unclear")
        if item["verdict"] in ("new", "flaked before", "maybe flaky") and args.triage:
            ck = f"{t['k']}-{t['q']}"
            if ck not in cache:
                from labeller import load_key
                from stackvitals.ci.triage import triage
                p = by_url.get(t["url"]) or {}
                one = {**item, "job_id": 1}
                triage([one], {1: p.get("log") or ""}, p.get("files_changed") or [],
                       {"ci": {"triage": {"provider": "gemini", "model": "", "url": ""}}}, load_key())
                cache[ck] = one.get("model")
                cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
            said = TRIAGE.get((cache.get(ck) or {}).get("caused_by_change"), said)
        triaged[key] = _grade(said, want[key])
    # Checks on the PR's own title, description or labels fit neither answer (the code is fine, the same PR fails again);
    # they are scored apart, with what each arm said.
    pr = {(t["k"], t["q"]) for t in truth if any(f["verdict"] == "PR details" for f in json.loads(
        (out / f"sv-{t['k']}" / f"ci_failure-{t['q']}.json").read_text(encoding="utf-8"))["failures"])}
    for r in arms.values():
        r["without_pr_details"] = _tally({k: v for k, v in r["_graded"].items() if k not in pr})
        r["without_pr_details"]["by_repo"] = by_repo([(repo_of[k], v == "right") for k, v in r["_graded"].items()
                                                       if k not in pr])
        r["pr_details_items"] = {"items": sum(k in pr for k in r["_graded"]),
                                 "said_flake_as_labelled": sum(r["_graded"][k] == "right" for k in r["_graded"] if k in pr)}
    result = {"items": len(truth), "repos": len({t["repo"] for t in truth}),
              "stackvitals_alone": _tally(alone), "stackvitals_with_triage": _tally(triaged),
              "pr_details_items": len(pr),
              "stackvitals_alone_without_pr_details": _tally({k: v for k, v in alone.items() if k not in pr}),
              "stackvitals_with_triage_without_pr_details": _tally({k: v for k, v in triaged.items() if k not in pr}),
              "arms": {a: {k: v for k, v in r.items() if k != "_graded"} for a, r in arms.items()}}
    pairs = {}
    for a, r in arms.items():
        g = {k: v for k, v in r["_graded"].items() if k not in pr}
        pairs[f"{a}_vs_alone"] = mcnemar(sum(g[k] == "right" and alone[k] != "right" for k in g),
                                         sum(g[k] != "right" and alone[k] == "right" for k in g))
    for x, y in (("a-sonnet", "b-sonnet"), ("a-haiku", "b-haiku")):
        if x in arms and y in arms:
            gx, gy = arms[x]["_graded"], arms[y]["_graded"]
            common = (set(gx) & set(gy)) - pr
            pairs[f"{x}_vs_{y}"] = mcnemar(sum(gx[k] == "right" and gy[k] != "right" for k in common),
                                           sum(gx[k] != "right" and gy[k] == "right" for k in common))
    result["paired"] = pairs
    (HERE / "results2.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
