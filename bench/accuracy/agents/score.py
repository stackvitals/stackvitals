"""Score the head-to-head: each arm's item answers against the flaky card's labels, how many of the labelled flaky jobs
its history answer found, and the GitHub calls it spent.

    python bench/accuracy/agents/score.py --out <head-to-head folder>

Writes results.json beside this script (answers reduced to right or wrong, no log text).
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from stackvitals.core.stats import wilson

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fair import mcnemar  # noqa: E402

ARMS = {"a": "general agent, live GitHub", "b": "the same agent with StackVitals' answers"}


def _norm(s: str) -> str:
    return " ".join(str(s or "").lower().split())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    truths = {int(p.stem.split("-")[1]): json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.out.glob("truth-*.json"))}
    out = {"repos": len(truths), "items": sum(len(t["items"]) for t in truths.values()), "arms": {},
           "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")}
    correct = {}  # (arm, repo index, question) -> right, for paired tests on the same questions
    for arm, name in ARMS.items():
        calls = [x for x in (args.out / f"calls-{arm}.log").read_text(encoding="utf-8").splitlines() if x.strip()] \
            if (args.out / f"calls-{arm}.log").exists() else []
        right, spent = Counter(), {}
        found, labelled, named = 0, 0, 0
        for k, t in truths.items():
            path = args.out / f"answers-{arm}-{k}.json"
            if not path.exists():
                continue
            got = json.loads(path.read_text(encoding="utf-8"))
            spent[t["repo"]] = sum(c.lower().startswith(f"repos/{t['repo'].lower()}/") for c in calls)
            answers = {a["q"]: a["answer"] for a in got.get("items") or []}
            for item in t["items"]:
                want = "change" if item["caused_by_change"] == "yes" else "flake"
                said = answers.get(item["q"], "unclear")
                right["right" if said == want else "unclear" if said == "unclear" else "wrong"] += 1
                right[f"{item['sample']}:{'right' if said == want else 'wrong'}"] += 1
                correct[(arm, k, item["q"])] = said == want
            jobs = [_norm(j.get("job")) for j in (got.get("history") or {}).get("jobs") or []]
            named += len(jobs)
            labelled += len(t["flaked_jobs_labelled"])
            found += sum(any(_norm(f) == j or _norm(f) in j or j in _norm(f) for j in jobs if j) for f in t["flaked_jobs_labelled"])
        n = right["right"] + right["wrong"] + right["unclear"]
        lo, hi = wilson(right["right"], n)
        out["arms"][arm] = {"who": name, "items_right": right["right"], "items": n, "share": round(right["right"] / n, 4) if n else None,
                            "low": round(lo, 4), "high": round(hi, 4), "unclear": right["unclear"],
                            "by_sample": {k: v for k, v in right.items() if ":" in k},
                            "flaky_jobs_found": found, "flaky_jobs_labelled": labelled, "jobs_named": named,
                            "github_calls": len(calls), "github_calls_by_repo": spent}
    # StackVitals' verdict alone, as a pull request comment would show it at the time: no agent, no log reading.
    alone = Counter()
    for k, t in truths.items():
        questions = {q["q"]: q for q in json.loads((args.out / f"questions-{k}.json").read_text(encoding="utf-8"))["items"]}
        for item in t["items"]:
            failures = json.loads((args.out / f"sv-{k}" / f"ci_failure-{item['q']}.json").read_text(encoding="utf-8"))["failures"]
            job = _norm(questions[item["q"]]["job"])
            verdict = next((f["verdict"] for f in failures if _norm(f["name"]).endswith(job)), "new")
            # "Maybe flaky" asks for one re-run before blaming the change: a lean toward a flake, counted apart too.
            said = {"known flaky": "flake", "outside failure": "flake", "already failing": "flake", "maybe flaky": "flake",
                    "new": "change"}.get(verdict, "unclear")
            alone["maybe flaky"] += verdict == "maybe flaky"
            want = "change" if item["caused_by_change"] == "yes" else "flake"
            alone["right" if said == want else "unclear" if said == "unclear" else "wrong"] += 1
            correct[("alone", k, item["q"])] = said == want
    n = alone["right"] + alone["unclear"] + alone["wrong"]
    out["stackvitals_alone"] = {"items_right": alone["right"], "items": n, "unclear": alone["unclear"], "wrong": alone["wrong"],
                                "maybe_flaky": alone["maybe flaky"], "github_calls": 0}
    keys = sorted({(k, q) for _arm, k, q in correct})

    def paired(x: str, y: str) -> dict:
        both = [key for key in keys if (x, *key) in correct and (y, *key) in correct]
        return {**mcnemar(sum(correct[(x, *key)] and not correct[(y, *key)] for key in both),
                          sum(correct[(y, *key)] and not correct[(x, *key)] for key in both)), "items": len(both)}
    out["paired_tests"] = {"agent_vs_agent_with_stackvitals": paired("a", "b"), "agent_vs_stackvitals_alone": paired("a", "alone")}
    # The cross-repo question, against the crawl's reading of 56 to 318 comparable repos.
    truth_path = args.out / "peer-truth.json"
    if truth_path.exists():
        truth = json.loads(truth_path.read_text(encoding="utf-8"))
        out["peers"] = {"repos": len(truth), "bars": "own share within 0.10, typical share within 0.05, percentile within 15"}
        for arm in ("a", "b"):
            path = args.out / f"peer-answers-{arm}.json"
            if not path.exists():
                continue
            log = args.out / f"calls-p{arm}.log"
            calls = [x for x in log.read_text(encoding="utf-8").splitlines() if x.strip()] if log.exists() else []
            hits = Counter()
            checked = []
            for a in json.loads(path.read_text(encoding="utf-8")):
                t = truth[a["repo"]]
                close = lambda got, want, tol: got is not None and abs(float(got) - want) <= tol  # noqa: E731
                hits["own"] += close(a.get("first_try_share"), t["first_try_share"], 0.10)
                hits["typical"] += close(a.get("peer_typical_share"), t["peer_median"], 0.05)
                hits["percentile"] += close(a.get("percentile"), t["percentile"], 15)
                checked.append(a.get("peer_repos_checked") or 0)
            out["peers"][arm] = {"who": ARMS[arm], **dict(hits), "peer_repos_checked": checked, "github_calls": len(calls)}
    (Path(__file__).with_name("results.json")).write_text(json.dumps(out, indent=1, sort_keys=True), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
