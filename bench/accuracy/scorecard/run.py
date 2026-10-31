"""StackVitals' own security checks next to OpenSSF Scorecard's published results, on repos drawn from the crawl with a
fixed seed (4 per language, 10 languages, 100+ stars, not archived). Scorecard's side is its public API (its weekly run,
no GitHub calls); ours runs through the GitHub API as the Action does.

    GITHUB_TOKEN=... python bench/accuracy/scorecard/run.py --out bench/accuracy/scorecard/results.json

A check agrees when both say pass or both say fail; Scorecard's -1 (inconclusive) and our "unknown" (can't read)
are left out of agreement and counted. Every disagreement is listed with both sides' evidence for reading."""
import argparse
import json
import os
import random
import sqlite3
import time
from pathlib import Path

import httpx

from stackvitals.ci.api import ActionsAPI
from stackvitals.security import probes

SEED, PER = 20261029, 4
LANGUAGES = ("Python", "TypeScript", "JavaScript", "Go", "Rust", "Java", "Kotlin", "C#", "PHP", "Ruby")
# Scorecard check -> (our probes, Scorecard's pass rule on its 0-10 score)
MAP = {"Dangerous-Workflow": (("hasDangerousWorkflowUntrustedCheckout", "hasDangerousWorkflowScriptInjection"), lambda s: s == 10),
       "Token-Permissions": (("topLevelPermissions",), lambda s: s >= 9),
       "Pinned-Dependencies": (("pinsDependencies",), lambda s: s == 10),
       "Branch-Protection": (("branchProtectionLevel",), lambda s: s >= 3),
       "Security-Policy": (("securityPolicyPresent",), lambda s: s > 0),
       "Signed-Releases": (("releasesAreSigned",), lambda s: s > 0),
       "SAST": (("sastToolConfigured",), lambda s: s > 0),
       "Binary-Artifacts": (("hasBinaryArtifacts",), lambda s: s == 10),
       "Fuzzing": (("fuzzed",), lambda s: s == 10),
       "CII-Best-Practices": (("hasOpenSSFBadge",), lambda s: s > 0),
       "Packaging": (("packagedWithAutomatedWorkflow",), lambda s: s == 10)}


def sample() -> list[tuple[str, str]]:
    db = sqlite3.connect(Path.home() / ".mergescout" / "mergescout.sqlite")
    rng, out = random.Random(SEED), []
    for lang in LANGUAGES:
        names = [r[0] for r in db.execute("select name from repos where language = ? and stars >= 100 and not archived "
                                          "order by name", (lang,))]
        out += [(lang, n) for n in rng.sample(names, min(PER, len(names)))]
    return out


def ours_vs_theirs(card: dict, results: list[dict]) -> dict:
    by = {r["probe"]: r for r in results}
    out = {}
    for name, (ids, rule) in MAP.items():
        check = next((c for c in card.get("checks") or [] if c.get("name") == name), None)
        theirs = None if not check or check.get("score", -1) < 0 else ("pass" if rule(check["score"]) else "fail")
        mine = [by[i]["result"] for i in ids if i in by]
        ours = "unknown" if not mine or "unknown" in mine else ("fail" if "fail" in mine else "pass")
        out[name] = {"scorecard": theirs, "ours": ours, "score": check.get("score") if check else None,
                     "reason": (check or {}).get("reason"),
                     "our_findings": [f["detail"] for i in ids if i in by for f in by[i]["findings"]][:3]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--repos-from", type=Path, help="re-run only the repos an earlier results file compared")
    a = ap.parse_args()
    tok = os.environ["GITHUB_TOKEN"]
    rows = []
    with httpx.Client(timeout=30, follow_redirects=True) as c:
        picked = sample()
        if a.repos_from:
            before = {r["repo"] for r in json.loads(a.repos_from.read_text(encoding="utf-8"))["repos"] if "checks" in r}
            picked = [(lang, repo) for lang, repo in picked if repo in before]
        for lang, repo in picked:
            card = c.get(f"https://api.scorecard.dev/projects/github.com/{repo}")
            if card.status_code != 200:
                rows.append({"repo": repo, "language": lang, "skipped": f"no Scorecard result ({card.status_code})"})
                continue
            api = ActionsAPI(tok, repo)
            t0 = time.perf_counter()
            try:
                branch = api._get(f"/repos/{repo}").get("default_branch") or "main"
                found, facts = probes.collect(api, repo, branch, get_json=lambda u: c.get(u).json())
            except Exception as exc:  # noqa: BLE001 - a repo we can't read is counted, not fatal
                rows.append({"repo": repo, "language": lang, "skipped": f"{type(exc).__name__}: {str(exc)[:120]}"})
                continue
            results = probes.verdicts(found, facts)
            rows.append({"repo": repo, "language": lang, "scorecard_date": card.json().get("date"),
                         "seconds": round(time.perf_counter() - t0, 1), "requests": api.requests if hasattr(api, "requests") else None,
                         "our_score": probes.score(results), "scorecard_score": card.json().get("score"),
                         "checks": ours_vs_theirs(card.json(), results)})
            print(repo, rows[-1]["our_score"], rows[-1]["scorecard_score"], flush=True)
    summary = {}
    for name in MAP:
        both = [r["checks"][name] for r in rows if "checks" in r]
        known = [x for x in both if x["scorecard"] and x["ours"] != "unknown"]
        summary[name] = {"compared": len(known), "agree": sum(x["scorecard"] == x["ours"] for x in known),
                         "scorecard_inconclusive": sum(1 for x in both if not x["scorecard"]),
                         "ours_unknown": sum(1 for x in both if x["ours"] == "unknown")}
    a.out.write_text(json.dumps({"seed": SEED, "repos": rows, "summary": summary}, indent=1) + "\n", encoding="utf-8")
    for name, s in summary.items():
        print(f"{name:20} agree {s['agree']}/{s['compared']}  scorecard -1: {s['scorecard_inconclusive']}  ours unknown: {s['ours_unknown']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
