"""How often the release signs fire on ordinary releases: the newest two stable versions of popular npm and PyPI
packages, compared the way the pull request check compares them. Release age is left out (it fires on every fresh
release by design); the other signs should stay rare on normal releases to be worth a look.

    python bench/accuracy/deps/release_signs.py run --per-ecosystem 150
    python bench/accuracy/deps/release_signs.py score

Packages come from the crawl's package map (~/.stackvitals/deps/deps-map.json), drawn seeded. Results:
release-signs-results.json."""
import argparse
import json
import random
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from stackvitals.deps import release  # noqa: E402

HERE = Path(__file__).resolve().parent
WORK = HERE.parent / ".work" / "release-signs"
SEED = 20261023
STABLE = re.compile(r"^\d+(\.\d+)*$")
KINDS = {"install script": "Adds an install script", "new dependencies": "New dependencies", "provenance dropped": "provenance"}


def latest_two(client: httpx.Client, system: str, name: str) -> tuple[str, str, str] | None:
    r = client.get(f"https://api.deps.dev/v3/systems/{system}/packages/{quote(name, safe='')}")
    if r.status_code != 200:
        return None
    vs = sorted((v for v in r.json().get("versions") or [] if STABLE.match(v["versionKey"]["version"]) and v.get("publishedAt")),
                key=lambda v: v["publishedAt"])
    if len(vs) < 2:
        return None
    return vs[-2]["versionKey"]["version"], vs[-1]["versionKey"]["version"], vs[-1]["publishedAt"]


def run(per_ecosystem: int) -> None:
    mapped = json.loads((Path.home() / ".stackvitals" / "deps" / "deps-map.json").read_text(encoding="utf-8"))["packages"]
    rng = random.Random(SEED)
    client = httpx.Client(timeout=30, headers={"User-Agent": "stackvitals-bench"})
    WORK.mkdir(parents=True, exist_ok=True)
    for eco, system in (("npm", "npm"), ("pypi", "pypi")):
        names = sorted(k.split(":", 1)[1] for k in mapped if k.startswith(eco + ":"))
        for name in rng.sample(names, min(per_ecosystem, len(names))):
            out = WORK / f"{eco}__{name.replace('/', '__')}.json"
            if out.exists():
                continue
            pair = latest_two(client, system, name)
            if not pair:
                out.write_text(json.dumps({"eco": eco, "name": name, "skipped": "fewer than two stable versions"}), encoding="utf-8")
                continue
            old, new, published = pair
            # Judged a day after its release, so the age sign never fires: this measures the other signs.
            when = datetime.fromisoformat(published.replace("Z", "+00:00")) + timedelta(days=3)
            signs = release.release_signs(client, eco, name, [old], [new], when)
            out.write_text(json.dumps({"eco": eco, "name": name, "old": old, "new": new, "published": published,
                                       "signs": signs}), encoding="utf-8")
    client.close()


def score() -> dict:
    rows = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(WORK.glob("*.json"))]
    judged = [r for r in rows if "signs" in r]
    out = {"releases": len(judged), "skipped": len(rows) - len(judged), "by_ecosystem": {}}
    for eco in ("npm", "pypi"):
        mine = [r for r in judged if r["eco"] == eco]
        fired = Counter(k for r in mine for k, text in KINDS.items() if any(text in s for s in r["signs"]))
        out["by_ecosystem"][eco] = {"releases": len(mine), "any_sign": sum(1 for r in mine if r["signs"]),
                                    **{k: fired.get(k, 0) for k in KINDS},
                                    "examples": [{"package": r["name"], "from": r["old"], "to": r["new"], "signs": r["signs"]}
                                                 for r in mine if r["signs"]][:8]}
    (HERE / "release-signs-results.json").write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("run").add_argument("--per-ecosystem", type=int, default=150)
    sub.add_parser("score")
    args = ap.parse_args(argv)
    if args.cmd == "run":
        run(args.per_ecosystem)
    else:
        print(json.dumps(score(), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
