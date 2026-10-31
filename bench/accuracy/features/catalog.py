"""How well Portal reads real catalog-info.yaml files: public repos found by GitHub code search, each root file read from
raw.githubusercontent.com (no API cost) and parsed by Portal's own parser.

    GH_TOKEN=... python bench/accuracy/features/catalog.py --out <folder> [--pages 2]

Reports the share parsed with no problems, the problems found, entity kinds and how many name an owner. File text is
untrusted data: it is only parsed with safe YAML, never run, and never published.
"""
import argparse
import collections
import json
import os
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from stackvitals.portal.descriptor import parse  # noqa: E402

API = "https://api.github.com"


def search(client: httpx.Client, pages: int) -> list[dict]:
    repos, seen = [], set()
    for page in range(1, pages + 1):
        resp = client.get(f"{API}/search/code", params={"q": "filename:catalog-info.yaml", "per_page": 100, "page": page})
        if resp.status_code != 200:
            break
        for item in resp.json().get("items") or []:
            name, path = item["repository"]["full_name"], item["path"]
            if path == "catalog-info.yaml" and name not in seen and not item["repository"].get("fork"):
                seen.add(name)
                repos.append({"repo": name, "branch": item["repository"].get("default_branch") or "HEAD"})
        time.sleep(7)  # code search allows about 10 requests a minute
    return repos


def score(texts: dict[str, str]) -> dict:
    kinds, problems, rows = collections.Counter(), collections.Counter(), []
    for repo, text in texts.items():
        try:
            entities, found = parse(text)
        except Exception as exc:  # a parser crash is a finding, not a stop
            entities, found = [], [f"crash: {type(exc).__name__}"]
        kinds.update(e.get("kind") or "?" for e in entities)
        problems.update(p.split(":")[0][:60] for p in found)
        rows.append({"repo": repo, "entities": len(entities), "problems": len(found),
                     "owners": sum(bool(e.get("owner")) for e in entities)})
    n = len(rows)
    clean = sum(r["entities"] and not r["problems"] for r in rows)
    return {"files": n, "parsed_clean": clean, "clean_share": round(clean / n, 4) if n else None,
            "with_entities": sum(bool(r["entities"]) for r in rows), "entities": sum(r["entities"] for r in rows),
            "entities_with_owner": sum(r["owners"] for r in rows), "kinds": dict(kinds.most_common()),
            "problems": dict(problems.most_common(15)), "repos": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--pages", type=int, default=2)
    args = ap.parse_args(argv)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    args.out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers=headers, timeout=30, follow_redirects=True) as client:
        repos = search(client, args.pages)
        texts = {}
        for r in repos:
            resp = httpx.get(f"https://raw.githubusercontent.com/{r['repo']}/{r['branch']}/catalog-info.yaml", timeout=30)
            if resp.status_code == 200 and len(resp.content) < 1_000_000:
                texts[r["repo"]] = resp.text
    result = score(texts)
    result["searched"] = len(repos)
    (args.out / "catalog-results.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "repos"}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
