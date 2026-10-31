"""Does the Portal stay light at 10,000 repos? A synthetic org (repos shaped like real catalog entries: owners, rules,
descriptors, scorecards) run through everything after the reads: scoring, the pages, the Backstage export and the
published file. Times and sizes go to scale-results.json beside this script.

    python bench/accuracy/portal/scale.py --repos 10000
"""
import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2] / "src"))
from stackvitals.core.store import published  # noqa: E402
from stackvitals.portal.export import entities_yaml  # noqa: E402
from stackvitals.portal.pages import render_catalog, render_catalog_html  # noqa: E402
from stackvitals.portal.scorecard import pack, rules_or_default, score_catalog  # noqa: E402


def repo(i: int, rng: random.Random) -> dict:
    owners = rng.choice([{"status": "valid", "owners": [f"@acme/team-{i % 40}"], "reasons": []},
                         {"status": "weak", "owners": ["@someone"], "reasons": ["no catch-all line"]},
                         {"status": "none", "owners": [], "reasons": ["no CODEOWNERS file"]}])
    return {"name": f"acme/svc-{i:05d}", "private": rng.random() < 0.7, "archived": rng.random() < 0.1, "fork": False,
            "language": rng.choice(["Python", "Go", "TypeScript", "Java", None]), "default_branch": "main",
            "pushed": "2026-10-01T00:00:00Z", "topics": [], "stars": rng.randint(0, 50), "description": f"Service {i}",
            "license": "MIT" if rng.random() < 0.6 else None, "rules": rng.choice([["pull_request"], [], None]),
            "protected": None, "owners": owners, "descriptor": {"present": rng.random() < 0.3, "entities": [], "problems": []},
            "files": {}, "modules": None, "docs": {"readme": True, "license": rng.random() < 0.6, "contributing": False,
                                                   "code_of_conduct": False, "org_defaults": []},
            "doc_pages": ["index.md", "setup.md"] if rng.random() < 0.4 else None, "runtime": ["container"],
            "ci": {"first_try_share": rng.random(), "pushes": rng.randint(0, 100)}, "reviews": None,
            "openssf": None, "scorecard": None, "checked": "2026-10-23T00:00:00Z"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repos", type=int, default=10000)
    args = ap.parse_args(argv)
    rng, now = random.Random(17), datetime(2026, 10, 23, tzinfo=timezone.utc)
    catalog = {"org": "acme", "mode": "private", "built_at": "2026-10-23T00:00:00Z", "complete": True,
               "repos": [repo(i, rng) for i in range(args.repos)], "campaigns": []}
    rules, exemptions, _ = rules_or_default(None)
    out, t = {"repos": args.repos}, time.perf_counter()
    score_catalog(catalog, rules, exemptions, now, None)
    out["score_s"] = round(time.perf_counter() - t, 2)
    t = time.perf_counter()
    text = json.dumps(published(catalog), indent=1)
    out["json_s"], out["catalog_json_mb"] = round(time.perf_counter() - t, 2), round(len(text) / 1e6, 2)
    out["catalog_json_compact_mb"] = round(len(json.dumps(published(catalog), separators=(",", ":"))) / 1e6, 2)
    import gzip
    packed = json.dumps(published(pack(catalog)), separators=(",", ":")).encode()
    out["app_json_packed_mb"], out["app_json_packed_gzip_mb"] = round(len(packed) / 1e6, 2), round(len(gzip.compress(packed)) / 1e6, 2)
    t = time.perf_counter()
    md = render_catalog(catalog, True)
    out["readme_s"], out["readme_mb"] = round(time.perf_counter() - t, 2), round(len(md) / 1e6, 2)
    t = time.perf_counter()
    page = render_catalog_html(catalog, True, set())
    out["html_s"], out["html_mb"] = round(time.perf_counter() - t, 2), round(len(page) / 1e6, 2)
    t = time.perf_counter()
    yml = entities_yaml(catalog["repos"], "https://acme.github.io/portal/")
    out["entities_s"], out["entities_mb"] = round(time.perf_counter() - t, 2), round(len(yml) / 1e6, 2)
    (HERE / "scale-results.json").write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
