"""The dependency evidence the daily pipeline publishes: upgrade ledger, package map, trend lines, vulnerability history."""
from pathlib import Path

from stackvitals.ci import bench as ci_bench

FILES = {"ledger": ("deps-ledger.json", "cells"), "map": ("deps-map.json", "packages"),
         "trends": ("deps-trends.json", "repos"), "osv": ("deps-osv.json", "packages"),
         "owners": ("deps-owners.json", "packages")}


def _validator(key: str):
    # A file without its main part is ignored, so a bad download can never break a check.
    return lambda d: d if isinstance(d, dict) and isinstance(d.get(key), (dict, list)) else None


def load_evidence(token: str | None, cache_dir: Path, client=None) -> dict | None:
    """All five files (each cached a day); None without the package map, which every dossier starts from."""
    parts = {name: ci_bench.load(token, cache_dir, client=client, name=file, url_env=f"STACKVITALS_DEPS_{name.upper()}_URL",
                                 validate=_validator(key), default_url=None)
             for name, (file, key) in FILES.items()}
    if not parts["map"]:
        return None
    return index_evidence(parts["ledger"] or {}, parts["map"], parts["trends"] or {}, parts["osv"] or {}, parts["owners"] or {})


def index_evidence(ledger: dict, mapped: dict, trends: dict, osv: dict, owners: dict | None = None) -> dict:
    cells = {}
    for c in ledger.get("cells") or []:
        if isinstance(c, dict) and c.get("package") and c.get("ecosystem"):
            cells.setdefault(f"{c['ecosystem']}:{c['package']}", []).append(c)
    return {"ledger": cells, "map": mapped.get("packages") or {},
            "trends": {k.lower(): v for k, v in (trends.get("repos") or {}).items()},
            "osv": osv.get("packages") or {}, "osv_complete": osv.get("complete", True),
            "owners": (owners or {}).get("packages") or {},
            "built_at": {"ledger": ledger.get("built_at"), "map": mapped.get("built_at"), "trends": trends.get("built_at"),
                         "osv": osv.get("built_at"), "owners": (owners or {}).get("built_at")}}


def load_ledger(token: str | None, cache_dir: Path, client=None) -> dict | None:
    """Only the upgrade ledger, indexed by "ecosystem:package" (cached a day); None when it can't be read."""
    file, key = FILES["ledger"]
    data = ci_bench.load(token, cache_dir, client=client, name=file, url_env="STACKVITALS_DEPS_LEDGER_URL",
                         validate=_validator(key), default_url=None)
    return index_evidence(data, {}, {}, {})["ledger"] if data else None
