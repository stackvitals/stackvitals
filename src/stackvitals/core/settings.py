""".github/stackvitals.toml from the repo's default branch, read once per job for every step: a conditional request makes
an unchanged file free, so a merged change applies on the next run. A missing file means the defaults; a failed read keeps
the last good settings, which live in the data branch (written only when they change, so quiet runs commit nothing)."""
import json
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from stackvitals.ci.api import ActionsAPI, APIError, NotFound, OutOfBudget
from stackvitals.core.config import FILE, parse
from stackvitals.core.time import iso

STATE = "settings/current.json"


@dataclass
class Settings:
    cfg: dict
    notes: list[str] = field(default_factory=list)
    text: str | None = None
    changed: bool = False


def _kept(root: Path) -> tuple[dict, bool]:
    """The last good text (and whether it came from this file, so its ETag can be trusted), else the old daily cache."""
    try:
        got = json.loads((root / STATE).read_text(encoding="utf-8"))
        if isinstance(got, dict):
            return got, True
    except (OSError, ValueError):
        pass
    try:
        old = json.loads((root / "ci" / "state.json").read_text(encoding="utf-8")).get("settings")
        if isinstance(old, dict):
            return {"text": old.get("text")}, False
    except (OSError, ValueError, AttributeError):
        pass
    return {}, False


def load(api, root: Path, now: datetime) -> Settings:
    kept, ours = _kept(root)
    try:
        content, etag = api.file_if_changed(FILE, None, kept.get("etag") if ours else None)
    except NotFound:
        content, etag = None, None
        text = None
    except (APIError, OutOfBudget) as exc:
        cfg, notes = parse(kept.get("text"))
        return Settings(cfg, notes + [f"{FILE} couldn't be read this run ({exc}); the last good settings were used."],
                        kept.get("text"))
    else:
        text = kept.get("text") if content is None else content.decode("utf-8", "replace")
    cfg, notes = parse(text)
    if text and notes and "couldn't be read" in notes[0] and kept.get("text") and kept.get("text") != text:
        # A typo must not switch the defaults (team automation is on by default) back on: keep the last good settings.
        good, _ = parse(kept["text"])
        return Settings(good, [notes[0].replace("the defaults were used", "the last good settings were used until it's fixed")],
                        kept.get("text"))
    changed = text != kept.get("text") or not ours
    if changed or etag != kept.get("etag"):
        path = root / STATE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"text": text, "etag": etag, "changed_at": iso(now) if changed else kept.get("changed_at")},
                                   indent=1), encoding="utf-8")
    return Settings(cfg, notes, text, changed and text != kept.get("text"))


def read(api) -> dict:
    """The settings without keeping anything (a pull request's check has no data branch); trouble means the defaults."""
    try:
        content, _etag = api.file_if_changed(FILE)
        return parse(content.decode("utf-8", "replace") if content else None)[0]
    except Exception:  # noqa: BLE001 - a pull request's check never fails over the settings file
        return parse(None)[0]


def prepare(env: dict, make_api=ActionsAPI):
    """The job's first act on a fresh checkout: the settings every step reads from `ws.cache["settings"]`."""
    def run(ws) -> None:
        api = make_api(env.get("STACKVITALS_TOKEN") or env.get("GITHUB_TOKEN"), ws.repo, max_requests=3)
        got = load(api, ws.path, ws.now)
        try:
            # The repo's details once per job (default branch, visibility, Pages), for the app's files; CI reuses them.
            ws.cache["repo_info"] = api._get(f"/repos/{ws.repo}")
        except Exception:  # noqa: BLE001 - without them CI reads them itself and the app files say less
            pass
        ws.cache["settings"], ws.cache["settings_notes"], ws.cache["settings_changed"] = got.cfg, got.notes, got.changed
        if got.notes:
            def summary():
                path = env.get("GITHUB_STEP_SUMMARY")
                if path:
                    with open(path, "a", encoding="utf-8") as f:
                        f.write("### StackVitals settings\n" + "\n".join(f"- {n}" for n in got.notes) + "\n")
            ws.after_commit(summary, "Settings")
    return run
