"""Look-alike names (typosquats) against the popular packages the evidence covers (Phase 16 M3): how many known
malicious packages the rule flags, and how many legitimate, less popular packages from real lockfiles it flags too.

    GH_TOKEN=... python bench/accuracy/deps/lookalike.py --deps <crawl deps folder> --work <work folder>

Malicious names: OpenSSF's malicious-packages repo (osv/malicious/npm and pypi; GitHub lists the first 100,000 npm
names). Legitimate names: every package in a few large public lockfiles, minus the popular set. Writes
lookalike-results.json beside this script (counts and the flagged legitimate names, which are public).
"""
import argparse
import json
import random
import sys
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
import stackvitals.deps.lookalike as rule  # noqa: E402
from stackvitals.deps.lockfiles import parse_lockfile  # noqa: E402

LOCKFILES = [("microsoft/vscode", "main", "package-lock.json"), ("microsoft/TypeScript", "main", "package-lock.json"),
             ("eslint/eslint", "main", "package-lock.json"), ("nodejs/node", "main", "tools/doc/package-lock.json"),
             ("mui/material-ui", "master", "package-lock.json"), ("pydantic/pydantic", "main", "uv.lock"),
             ("python-poetry/poetry", "main", "poetry.lock"), ("astral-sh/ruff", "main", "uv.lock"),
             ("fastapi/fastapi", "master", "uv.lock"), ("encode/httpx", "master", "uv.lock")]


def malicious(work: Path) -> dict[str, list[str]]:
    out = {}
    for eco in ("npm", "pypi"):
        tree = json.loads((work / f"{eco}-tree.json").read_text(encoding="utf-8"))
        out[eco] = [e["path"] for e in tree["tree"] if e["type"] == "tree"]
    return out


def legit(popular: dict[str, set[str]]) -> dict[str, list[str]]:
    out = {"npm": set(), "pypi": set()}
    for repo, branch, path in LOCKFILES:
        resp = httpx.get(f"https://raw.githubusercontent.com/{repo}/{branch}/{path}", timeout=60, follow_redirects=True)
        if resp.status_code != 200:
            continue
        for eco, name, _v in parse_lockfile(path, resp.text):
            out[eco].add(name)
    return {eco: sorted(n for n in names if rule._norm(eco, n) not in {rule._norm(eco, p) for p in popular[eco]})
            for eco, names in out.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--deps", type=Path, required=True)
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--sample", type=int, default=20000, help="malicious npm names sampled (seeded)")
    args = ap.parse_args(argv)
    mapped = json.loads((args.deps / "deps-map.json").read_text(encoding="utf-8"))["packages"]
    popular = {"npm": set(), "pypi": set()}
    for key in mapped:
        eco, name = key.split(":", 1)
        if eco in popular:
            popular[eco].add(name)
    bad = malicious(args.work)
    bad["npm"] = random.Random(7).sample(bad["npm"], min(args.sample, len(bad["npm"])))
    good = legit(popular)
    out = {"popular": {e: len(v) for e, v in popular.items()}, "by_min_length": {}}
    for minimum in (5, 6, 7):
        rule.MIN_LENGTH = minimum
        row = {}
        for eco in ("npm", "pypi"):
            hits = [n for n in bad[eco] if rule.lookalike(eco, n, popular)]
            false = [(n, rule.lookalike(eco, n, popular)) for n in good[eco] if rule.lookalike(eco, n, popular)]
            row[eco] = {"malicious": len(bad[eco]), "malicious_flagged": len(hits),
                        "legit": len(good[eco]), "legit_flagged": len(false), "legit_flagged_names": false[:20],
                        "malicious_examples": hits[:10]}
        out["by_min_length"][str(minimum)] = row
    # The product flags a look-alike only under LOW_DOWNLOADS a week: checked on every flagged legitimate name and up to
    # 40 flagged malicious ones per ecosystem (cut-off 5, the product's).
    rule.MIN_LENGTH = 5
    gated = {}
    with httpx.Client(timeout=30, headers={"User-Agent": "stackvitals-bench"}) as client:
        for eco in ("npm", "pypi"):
            legit_hits = [n for n in good[eco] if rule.lookalike(eco, n, popular)]
            bad_hits = random.Random(7).sample([n for n in bad[eco] if rule.lookalike(eco, n, popular)],
                                               min(40, sum(1 for n in bad[eco] if rule.lookalike(eco, n, popular))))
            count = lambda names: [rule.weekly_downloads(eco, n, client) for n in names]  # noqa: E731
            lg, bd = count(legit_hits), count(bad_hits)
            gated[eco] = {"legit_flagged": len(legit_hits), "legit_still_flagged": sum(d is None or d < rule.LOW_DOWNLOADS for d in lg),
                          "legit_downloads_min": min((d for d in lg if d is not None), default=None),
                          "malicious_checked": len(bad_hits), "malicious_still_flagged": sum(d is None or d < rule.LOW_DOWNLOADS for d in bd),
                          "malicious_downloads_max": max((d for d in bd if d is not None), default=None)}
    out["with_downloads"] = gated
    (HERE / "lookalike-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(gated, indent=1))
    print(json.dumps({m: {e: {k: v for k, v in r.items() if "names" not in k and "examples" not in k} for e, r in row.items()}
                      for m, row in out["by_min_length"].items()}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
