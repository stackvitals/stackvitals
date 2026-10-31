"""Data health: is the data current, did collection finish, how far back does each history go, and what was dropped.
Written once a run (docs/health.json) from each step's result, the connectors' status and the data branch itself."""
import json
from pathlib import Path

from stackvitals.core.store import DAY_FILE, STREAMS, published, write_if_changed
from stackvitals.core.time import iso

COUNTS = 8  # the numbers kept from a step's result


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _stats(result) -> dict | None:
    """The part of a step's result that says what it collected: the result itself, or a "collect" inside it (CI Health)."""
    if not isinstance(result, dict):
        return None
    inner = result.get("collect")
    return inner if "complete" not in result and isinstance(inner, dict) else None


def _counts(result) -> dict:
    """The plain numbers in a step's result (runs read, requests used, ...), never its nested detail."""
    if not isinstance(result, dict):
        return {}
    nums = {k: v for k, v in {**result, **(_stats(result) or {})}.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return dict(list(nums.items())[:COUNTS])


def _complete(result):
    for part in (result, _stats(result)):
        if isinstance(part, dict) and isinstance(part.get("complete"), bool):
            return part["complete"]
    return None


def _entry(old: dict, kind: str, at: str, error: str | None, complete, read: dict) -> dict:
    """One source's line: a failure keeps the last good run and the first failing one, so "since when" stays true."""
    return {"kind": kind, "last_try": at, "last_ok": old.get("last_ok") if error else at,
            "failing_since": (old.get("failing_since") or at) if error else None, "error": error,
            "complete": complete, "read": read}


def _history(root: Path) -> dict:
    out = {}
    for stream, keeps in STREAMS.items():
        folder = root / stream
        if not folder.is_dir():
            continue
        days = sorted((m.group(1), p.stat().st_size) for p in folder.iterdir() if (m := DAY_FILE.match(p.name)))
        if days:
            out[stream] = {"oldest": days[0][0], "newest": days[-1][0], "files": len(days),
                           "bytes": sum(size for _d, size in days), "keeps_days": keeps}
    return out


def write_health(ws, results: dict, errors: dict, house: dict) -> dict:
    docs = ws.path / "docs"
    old = _read(docs / "health.json")
    at = iso(ws.now)
    sources = dict(old.get("sources") or {})  # a step that didn't run this time keeps its last line
    for label in {*results, *errors}:
        result = results.get(label)
        complete = _complete(result)
        sources[label] = _entry(sources.get(label) or {}, "module", at, errors.get(label), complete, _counts(result))
    for entry in ((_read(docs / "connectors.json").get("connectors")) or {}).values():
        if not isinstance(entry, dict) or not entry.get("as_of"):
            continue  # a tested service that isn't pulled (chat webhooks, the bucket)
        name = entry.get("name") or "connector"
        sources[name] = _entry(sources.get(name) or {}, "connector", entry["as_of"], entry.get("error"),
                               entry.get("complete"), entry.get("rows") or {})
    removed = {k: v for k, v in ((house or {}).get("removed") or {}).items() if v}
    capped = {k: v for k, v in ((house or {}).get("dropped") or {}).items() if v}
    # The last time retention or the size cap removed anything is remembered, so a gap it left is explained.
    dropped = {"at": at, "retention": removed, "size_cap": capped} if removed or capped else old.get("dropped")
    out = {"as_of": at, "sources": dict(sorted(sources.items())), "history": _history(ws.path), "dropped": dropped}
    # Times and this run's counts alone never rewrite the file (a run would commit just to move them), as with the
    # modules' own files; a new failure, a recovery, finishing the history or a new day of data do.
    if docs.is_dir() and _steady(out) != _steady(old):
        write_if_changed(docs / "health.json", published(out))
    return out


def _steady(h: dict) -> dict:
    return {"sources": {k: {f: v for f, v in e.items() if f not in ("last_try", "last_ok", "read")}
                        for k, e in (h.get("sources") or {}).items()},
            # Sizes on disk can move with how a checkout writes line ends; the days held are what count.
            "history": {k: {f: v for f, v in e.items() if f != "bytes"} for k, e in (h.get("history") or {}).items()},
            "dropped": {k: v for k, v in (h.get("dropped") or {}).items() if k != "at"}}
