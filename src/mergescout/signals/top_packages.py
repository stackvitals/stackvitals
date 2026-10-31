"""The most-used npm and PyPI packages (by repos depending on them, from ecosyste.ms), so the evidence covers what people
add, not only what crawled repos happen to upgrade."""
from mergescout.signals.bump_ledger import valid_name
from mergescout.signals.bumps import _norm
from mergescout.signals.deps_map import http_get_json

REGISTRIES = {"npm": "npmjs.org", "pypi": "pypi.org"}
URL = ("https://packages.ecosyste.ms/api/v1/registries/{registry}/packages"
       "?sort=dependent_repos_count&order=desc&per_page=100&page={page}")


def fetch_top(n: int = 1000, get_json=None) -> list[tuple[str, str]]:
    """The top n of each registry, most-used first; a page that fails ends that registry's list for today."""
    get_json = get_json or http_get_json
    out = []
    for eco, registry in REGISTRIES.items():
        for page in range(1, -(-n // 100) + 1):
            try:
                rows = get_json(URL.format(registry=registry, page=page))
            except Exception:  # noqa: BLE001
                break
            if not isinstance(rows, list) or not rows:
                break
            out += [(eco, _norm(eco, r["name"])) for r in rows
                    if isinstance(r, dict) and isinstance(r.get("name"), str) and valid_name(eco, r["name"])]
    return list(dict.fromkeys(out))
