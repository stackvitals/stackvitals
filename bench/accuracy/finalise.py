"""Put the adjudicated labels (final/<card>.jsonl) where each card's scorer reads them, keeping the first labeller's
labels and Gemini's beside them, so a card is re-scored on the final labels and still shows both labellers.

    python bench/accuracy/finalise.py dora-sources --work bench/accuracy/.work
    python bench/accuracy/finalise.py community --work bench/accuracy/.work
    python bench/accuracy/finalise.py flaky --work bench/accuracy/.work

dora-sources and flaky get a copy of their work folder (<card>-final) with the final labels in the files their scorers
read; community's frozen label files gain claude_kind and gemini_kind columns, and kind becomes the final label.
"""
import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _jsonl(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def dora(work: Path, name: str = "dora-sources") -> Path:
    home, out = work / name, work / f"{name}-final"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(home, out, ignore=shutil.ignore_patterns("gemini-cache", "adjudicate-*", "labels-*.jsonl"))
    first = {r["repo"]: r for p in sorted(home.glob("labels-[0-9].jsonl")) for r in _jsonl(p)}
    final = {r["id"]: r for r in _jsonl(work / "final" / f"{name}.jsonl")}
    merged = []
    for repo, lab in sorted(first.items()):
        lab = {**lab, "workflows": dict(lab["workflows"])}
        if repo in final and final[repo].get("sources"):
            lab["sources"] = final[repo]["sources"].split()
        for path in lab["workflows"]:
            key = f"{repo}|{path}"
            if key in final and final[key].get("ships"):
                lab["workflows"][path] = final[key]["ships"]
        merged.append(lab)
    _write_jsonl(out / "labels-0.jsonl", merged)
    return out


def community(work: Path) -> list[Path]:
    done = []
    for name, card in (("main", "community-main"), ("validation", "community-validation")):
        final = {int(r["id"]): r for r in _jsonl(work / "final" / f"{card}.jsonl")}
        gemini = {int(r["id"]): r for r in csv.DictReader((HERE / "community" / f"labels-gemini-{name}.csv").open(encoding="utf-8"))}
        path = HERE / "community" / f"labels-{name}.csv"
        rows = list(csv.DictReader(path.open(encoding="utf-8")))
        fields = list(rows[0])
        for extra in ("claude_kind", "gemini_kind"):
            if extra not in fields:
                fields.append(extra)
        for r in rows:
            i = int(r["id"])
            r["claude_kind"] = r.get("claude_kind") or r["kind"]
            r["gemini_kind"] = gemini.get(i, {}).get("kind", "")
            r["kind"] = final.get(i, {}).get("kind", r["kind"])
        with path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        done.append(path)
    return done


def flaky(work: Path) -> Path:
    home, out = work / "flaky", work / "flaky-final"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(home, out, ignore=shutil.ignore_patterns("gemini-cache", "adjudicate-*", "old-labels"))
    fields = ("cause", "caused_by_change", "own_failure")
    for name, card in (("labels.jsonl", "flaky"), ("asof-labels.jsonl", "masking")):
        final = {str(r["id"]): r for r in _jsonl(work / "final" / f"{card}.jsonl")}
        rows = []
        for lab in _jsonl(home / name):
            got = final.get(str(lab["id"]), {})
            rows.append({**lab, **{k: got[k] for k in fields if got.get(k)}})
        _write_jsonl(out / name, rows)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("card", choices=("dora-sources", "dora-sources-more", "community", "flaky"))
    ap.add_argument("--work", type=Path, required=True)
    args = ap.parse_args(argv)
    result = (dora(args.work, args.card) if args.card.startswith("dora-sources")
              else {"community": community, "flaky": flaky}[args.card](args.work))
    print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
