"""The opt-in model triage (`ci/triage.py`) on the agent card's 20 failures: what StackVitals alone said, and what the
model reading the same log excerpt and changed files said, each against the label.

    python bench/accuracy/agents/triage_check.py --out <agents work folder> --flaky-home <flaky work folder>

One Gemini call per item the rules leave undecided (GEMINI_API_KEY, free tier); answers are cached in the work folder.
Writes triage-results.json beside this script (counts only).
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from labeller import load_key  # noqa: E402

from stackvitals.ci.triage import triage  # noqa: E402

ON = {"ci": {"triage": {"provider": "gemini", "model": "", "url": ""}}}
SAID = {"known flaky": "flake", "outside failure": "flake", "already failing": "flake", "maybe flaky": "flake", "new": "change"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--flaky-home", type=Path, required=True)
    args = ap.parse_args(argv)
    items = [json.loads(x) for x in (args.flaky_home / "items.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    items = [i for i in items if i.get("sample") != "none"]
    cache_path = args.out / "triage-cache.json"
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    key, tally = load_key(), Counter()
    for k in range(5):
        truth = json.loads((args.out / f"truth-{k}.json").read_text(encoding="utf-8"))
        questions = {q["q"]: q for q in json.loads((args.out / f"questions-{k}.json").read_text(encoding="utf-8"))["items"]}
        for t in truth["items"]:
            want = "change" if t["caused_by_change"] == "yes" else "flake"
            found = json.loads((args.out / f"sv-{k}" / f"ci_failure-{t['q']}.json").read_text(encoding="utf-8"))["failures"]
            job = questions[t["q"]]["job"]
            v = next((f for f in found if f["name"].endswith(job)), {"verdict": "new", "detail": ""})
            alone = SAID.get(v["verdict"], "unclear")
            tally[f"alone:{'right' if alone == want else 'unclear' if alone == 'unclear' else 'wrong'}"] += 1
            item = {"kind": "job", "job_id": 1, "name": job, "verdict": v["verdict"], "detail": v.get("detail") or ""}
            ck = f"{k}-{t['q']}"
            if ck not in cache and item["verdict"] in ("new", "flaked before", "maybe flaky"):
                src = items[t["item"] - 1]
                triage([item], {1: src.get("log") or ""}, src.get("files_changed") or [], ON, key)
                cache[ck] = item.get("model")
                cache_path.write_text(json.dumps(cache, indent=1), encoding="utf-8")
            model = (cache.get(ck) or {}).get("caused_by_change")
            if model:
                said = {"yes": "change", "no": "flake"}.get(model, "unclear")
                tally[f"model:{'right' if said == want else 'unclear' if said == 'unclear' else 'wrong'}"] += 1
                tally[f"model_on_alone_{'right' if alone == want else 'not_right'}:{'right' if said == want else 'not_right'}"] += 1
    out = dict(sorted(tally.items()))
    (HERE / "triage-results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
