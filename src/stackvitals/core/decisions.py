"""Decisions people make about items (quarantine a test, mute a job, snooze a finding, exclude a pull request), written on
GitHub as `/stackvitals` commands or as a request block from the app. The data branch keeps every decision in an
append-only log (who, when, why, until when, from where); the current state is the newest decision per item, and a
temporary one drops out on its review date, so nothing stays switched off by accident."""
import json
import re
import shlex
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from stackvitals.core.time import iso

LOG = "decisions/log.ndjson"
STATE = "decisions/state.json"
# Which items each verb applies to, and how long a temporary decision lasts unless the command says (None: no end).
VERBS = {
    "quarantine": (("test",), 30), "unquarantine": (("test",), None),
    "mute": (("test", "job"), 30), "unmute": (("test", "job"), None),
    "acknowledge": (("test", "job", "finding"), None), "snooze": (("finding",), 14),
    "reopen": (("test", "job", "finding", "package"), None),
    "exclude": (("pr",), None), "include": (("pr",), None), "accept": (("package", "rerun"), 30),
    "confirm": (("test", "job"), None), "dispute": (("test", "job"), None),
}
KINDS = ("test", "job", "finding", "pr", "package", "rerun")
# Verbs that only undo an earlier decision: nothing is in force after them.
UNDO = {"unquarantine", "unmute", "reopen", "include"}
# Verbs that say whether StackVitals' verdict was right: logged with what it said then, never in force.
FEEDBACK = {"confirm", "dispute"}
_DURATION = re.compile(r"^(\d{1,3})\s*(d|day|days|w|week|weeks)$", re.I)
REASON_MAX = 200
ID_MAX = 500


class CommandError(ValueError):
    pass


@dataclass(frozen=True)
class Decision:
    verb: str
    kind: str
    id: str
    until: str | None
    reason: str


@dataclass
class Request:
    changes: list[Decision]
    settings: dict
    golden: dict | None = None  # a Portal golden path to run: {"path": id, "inputs": {...}}
    check: list | str | None = None  # connectors to test: "all" or names (connectors/check.py)
    resync: list | None = None  # services to read again: [{"source": "jira", "since": "2026-09-01" or None}]


def _until(words: list[str], today: date) -> tuple[str | None, list[str]]:
    """`for 14d`, `for 2 weeks` or `until 2026-12-01` anywhere in the words; the rest is returned untouched."""
    for i, word in enumerate(words):
        low = word.lower()
        if low == "until" and i + 1 < len(words):
            try:
                return date.fromisoformat(words[i + 1]).isoformat(), words[:i] + words[i + 2:]
            except ValueError:
                raise CommandError(f"`until` needs a date like 2026-12-31, not {words[i + 1]!r}.") from None
        if low == "for" and i + 1 < len(words):
            joined, used = words[i + 1], 2
            if i + 2 < len(words) and not _DURATION.match(joined) and _DURATION.match(f"{joined} {words[i + 2]}"):
                joined, used = f"{joined} {words[i + 2]}", 3
            m = _DURATION.match(joined)
            if m:
                days = int(m[1]) * (7 if m[2].lower().startswith("w") else 1)
                return (today + timedelta(days=days)).isoformat(), words[:i] + words[i + used:]
    return None, words


def _target(word: str) -> tuple[str, str] | None:
    if re.fullmatch(r"#\d+", word):
        return "pr", word[1:]
    kind, sep, ident = word.partition(":")
    if sep and kind in KINDS and ident:
        return kind, ident[1:] if kind == "pr" and ident.startswith("#") else ident
    return None


def _decision(verb: str, kind: str, ident: str, until: str | None, reason: str, today: date) -> Decision:
    kinds, default_days = VERBS[verb]
    if kind not in kinds and verb in FEEDBACK:
        raise CommandError(f"Say which verdict: /stackvitals {verb} test:<id> or job:\"<name>\", as the comment names it.")
    if kind not in kinds:
        raise CommandError(f"`{verb}` is for {' or '.join(kinds)} items, not {kind}.")
    if len(ident) > ID_MAX or any(ord(ch) < 32 or ord(ch) == 127 for ch in ident):
        raise CommandError(f"An item id has line breaks or control characters, or is over {ID_MAX} characters.")
    if until is None and default_days:
        until = (today + timedelta(days=default_days)).isoformat()
    clean = " ".join((reason or "").split())[:REASON_MAX]
    return Decision(verb, kind, ident.strip(), until, clean)


def parse_command(text: str, today: date, default: tuple[str, str] | None = None) -> list[Decision]:
    """Every line that starts with `/stackvitals <verb>`: its targets (`test:<id>`, `job:"<name>"`, `finding:<key>`,
    `#<pr>`), else the item the issue is about; `for 14d` or `until DATE`; a reason after `because` or `--`."""
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line.lower().startswith("/stackvitals"):
            continue
        rest = line[len("/stackvitals"):].strip()
        reason = ""
        for marker in (" because ", " -- "):
            if marker in f" {rest} ":
                rest, _, reason = f" {rest} ".partition(marker)
                rest = rest.strip()
                break
        try:
            words = shlex.split(rest)
        except ValueError:
            raise CommandError("A quote in that command isn't closed.") from None
        if not words or words[0].lower() not in VERBS:
            raise CommandError(f"Known commands: {', '.join(VERBS)}. Example: /stackvitals quarantine for 14d because ...")
        verb = words[0].lower()
        until, words = _until(words[1:], today)
        targets = [t for t in (_target(w) for w in words) if t]
        if not targets and default and default[0] == "pr" and any(w.lower() == "rerun" for w in words):
            # `/stackvitals accept rerun` on a pull request: its green re-run is accepted (the verdict's strict mode).
            targets = [("rerun", default[1])]
        if not targets and default:
            targets = [default]
        if not targets:
            raise CommandError(f"Say which item: /stackvitals {verb} test:<id>, job:\"<name>\", finding:<key> or #<pr>.")
        out += [_decision(verb, kind, ident, until, reason, today) for kind, ident in targets]
    return out


def parse_request(body: str, today: date) -> Request | None:
    """The fenced ```stackvitals block the app puts in a request issue (or a dispatch input): JSON with changes and
    settings. None when there is no block."""
    m = re.search(r"```stackvitals\s*\n(.*?)\n```", body or "", re.S)
    if not m:
        return None
    try:
        doc = json.loads(m[1])
    except ValueError:
        raise CommandError("The request block isn't valid JSON; nothing was changed.") from None
    if not isinstance(doc, dict) or doc.get("version") != 1:
        raise CommandError("The request block has an unknown version; nothing was changed.")
    changes = []
    for c in doc.get("changes") or []:
        if not isinstance(c, dict) or c.get("verb") not in VERBS or not isinstance(c.get("id"), str):
            raise CommandError("A change in the request block is incomplete; nothing was changed.")
        until = c.get("until")
        if until is not None:
            try:
                until = date.fromisoformat(str(until)).isoformat()
            except ValueError:
                raise CommandError(f"`until` must be a date like 2026-12-31, not {until!r}.") from None
        changes.append(_decision(c["verb"], str(c.get("kind")), c["id"], until, str(c.get("reason") or ""), today))
    settings = doc.get("settings") or {}
    if not isinstance(settings, dict):
        raise CommandError("The settings in the request block must be key: value pairs; nothing was changed.")
    golden = doc.get("golden")
    if golden is not None and not (isinstance(golden, dict) and isinstance(golden.get("path"), str)
                                   and isinstance(golden.get("inputs") or {}, dict)):
        raise CommandError("A golden path request needs a path and its inputs; nothing was run.")
    check = doc.get("check")
    if check is not None and check != "all" and not (isinstance(check, list) and check
                                                     and all(isinstance(x, str) and x.strip() for x in check)):
        raise CommandError('`check` must be "all" or a list of connector names, like ["jira", "slack"]; nothing was checked.')
    resync = doc.get("resync")
    if resync is not None:
        ok = isinstance(resync, list) and resync and all(isinstance(r, dict) and isinstance(r.get("source"), str) and "since" in r
                                                        for r in resync)
        try:
            for r in resync if ok else []:
                if r["since"] is not None:
                    date.fromisoformat(str(r["since"]))
        except ValueError:
            ok = False
        if not ok:
            raise CommandError('`resync` must be a list like [{"source": "jira", "since": "2026-09-01"}] (since may be null for '
                               "the whole window); nothing was read again.")
        resync = [{"source": r["source"], "since": r["since"]} for r in resync]
    return Request(changes, settings, {"path": golden["path"], "inputs": golden.get("inputs") or {}} if golden else None,
                   check, resync)


class Store:
    """decisions/ in the data branch: the log is only appended to; state.json is rebuilt from it."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def log(self) -> list[dict]:
        try:
            text = (self.root / LOG).read_text(encoding="utf-8")
        except OSError:
            return []
        return [json.loads(line) for line in text.splitlines() if line.strip()]

    def record(self, decisions: list[Decision], by: str, source: str, now: datetime, seen: dict | None = None) -> list[dict]:
        """Append decisions; feedback rows carry what StackVitals said about the item then (`seen`, by (kind, id))."""
        rows = [{"at": iso(now), "by": by, "source": source, **asdict(d),
                 **({"seen": (seen or {}).get((d.kind, d.id))} if d.verb in FEEDBACK else {})} for d in decisions]
        if not rows:
            return []
        path = self.root / LOG
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as f:
            f.writelines(json.dumps(r, separators=(",", ":"), ensure_ascii=False) + "\n" for r in rows)
        latest = {}
        for row in self.log():
            if row["verb"] not in FEEDBACK:
                latest[f"{row['kind']}:{row['id']}"] = row
        (self.root / STATE).write_text(json.dumps(latest, indent=1, sort_keys=True, ensure_ascii=False), encoding="utf-8")
        return rows

    def state(self, today: date) -> dict[str, dict]:
        """The newest decision per item, without those whose review date has passed."""
        try:
            latest = json.loads((self.root / STATE).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            latest = {}
        day = today.isoformat()
        return {k: v for k, v in latest.items() if not v.get("until") or v["until"] >= day}

    def ids(self, verb: str, kind: str, today: date) -> set[str]:
        return {v["id"] for v in self.state(today).values() if v["verb"] == verb and v["kind"] == kind}

    def feedback(self) -> list[dict]:
        return [row for row in self.log() if row.get("verb") in FEEDBACK]


def verdict_accuracy(rows: list[dict]) -> dict:
    """How often people confirmed StackVitals' verdict, per the verdict it gave then (known flaky, flaked before,
    already failing, new): the newest feedback per person and item counts once, with a 95% range."""
    from stackvitals.core.stats import wilson
    latest = {}
    for r in rows:
        latest[(r.get("by"), r.get("kind"), r.get("id"))] = r
    out = {}
    for r in latest.values():
        seen = r.get("seen") or {}
        state = seen.get("verdict") or seen.get("state") or "unknown"
        cell = out.setdefault(state, {"confirmed": 0, "disputed": 0})
        cell["confirmed" if r["verb"] == "confirm" else "disputed"] += 1
    for cell in out.values():
        n = cell["confirmed"] + cell["disputed"]
        lo, hi = wilson(cell["confirmed"], n)
        cell.update(n=n, share=round(cell["confirmed"] / n, 4), low=round(lo, 4), high=round(hi, 4))
    return out


EXCLUDE_LABEL = "stackvitals: exclude"


def excluded_prs(state: dict, prs: list[dict]) -> set[int]:
    """Pull requests the team left out of the numbers: an `exclude` decision or the label, unless someone said `include`."""
    said = {int(v["id"]): v["verb"] for v in state.values() if v.get("kind") == "pr" and str(v.get("id")).isdigit()}
    labelled = {p["n"] for p in prs if EXCLUDE_LABEL in (p.get("lb") or [])}
    return {n for n in labelled | set(said) if said.get(n, "exclude") == "exclude"}


def drop_prs(flow: dict, numbers: set[int]) -> dict:
    """The pull request history without the excluded ones, and how many were left out."""
    if not numbers:
        return flow
    keep = lambda rows: [p for p in rows or [] if p.get("n") not in numbers]
    gone = sum(1 for p in (flow.get("open") or []) + (flow.get("closed") or []) if p.get("n") in numbers)
    return {**flow, "open": keep(flow.get("open")), "closed": keep(flow.get("closed")), "excluded": gone}


def visible(root: Path, flow: dict, today: date) -> dict:
    """The pull request history every module computes from: without the ones the team excluded."""
    prs = (flow.get("open") or []) + (flow.get("closed") or [])
    return drop_prs(flow, excluded_prs(Store(root).state(today), prs))
