"""Phase 16 baseline for staging against production: on the DORA card's labelled repos, the GitHub environments each
has, read as the product reads them today (production names only; everything else hidden).

    GH_TOKEN=... python bench/accuracy/dora/environments.py

Writes environments-results.json beside this script (counts and environment names, which are public).
"""
import csv
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from stackvitals.core.config import DELIVERY  # noqa: E402

PRODUCTION = {x.lower() for x in DELIVERY["production"]}
STAGING = re.compile(r"(?i)\b(stag(e|ing)|pre-?prod|preview|dev(elop(ment)?)?|test(ing)?|qa|uat|sandbox|review|canary|beta)\b")
# Environments that publish a package or site rather than run a service.
PUBLISH = re.compile(r"(?i)\b(pypi|npm|crates?|nuget|maven|rubygems|github-pages|pages|release|publish|docs?|registry|docker)\b")


def kind(name: str) -> str:
    low = name.lower()
    first = re.split(r"[\s\-–_/:]+", low, maxsplit=1)[0]
    if low in PRODUCTION or first in PRODUCTION:
        return "production"
    if STAGING.search(name):
        return "staging"
    if PUBLISH.search(name):
        return "publish"
    return "other"


def main() -> int:
    repos = sorted({r["repo"] for f in ("sources-labels.csv", "sources-more-labels.csv")
                    for r in csv.DictReader((HERE / f).open(encoding="utf-8"))})
    headers = {"Authorization": f"Bearer {os.environ['GH_TOKEN']}", "Accept": "application/vnd.github+json"}
    per_repo = {}
    with httpx.Client(headers=headers, timeout=30) as client:
        for repo in repos:
            resp = client.get(f"https://api.github.com/repos/{repo}/environments", params={"per_page": 100})
            names = [e["name"] for e in resp.json().get("environments") or []] if resp.status_code == 200 else None
            per_repo[repo] = names
    read = {r: n for r, n in per_repo.items() if n is not None}
    kinds = {r: Counter(kind(x) for x in n) for r, n in read.items()}
    has = lambda k: sum(1 for c in kinds.values() if c[k])  # noqa: E731
    out = {"repos": len(repos), "read": len(read), "with_environments": sum(1 for n in read.values() if n),
           "with_production": has("production"), "with_staging": has("staging"), "with_publish": has("publish"),
           "with_staging_and_production": sum(1 for c in kinds.values() if c["staging"] and c["production"]),
           "with_staging_only": sum(1 for c in kinds.values() if c["staging"] and not c["production"]),
           "names": {r: n for r, n in sorted(read.items()) if n},
           "product_today": "production names (production, prod, live, first word) shown; all others hidden"}
    (HERE / "environments-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "names"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
