"""Agents propose, people submit: the same prefilled request issue the app opens, for a settings change and/or a
`/stackvitals` command, checked first with the Action's own parsers so a bad value never reaches GitHub. Nothing is sent:
a person opens the link and presses Submit, and the workflow applies it if they have the access."""
import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime, timezone
from urllib.parse import quote

from stackvitals.core import decisions as dec
from stackvitals.core.tomledit import EditError, apply

URL_MAX = 7500


class ProposalError(ValueError):
    pass


def body(changes: list[dict], settings: dict, note: str = "") -> str:
    """The issue text, the same as the app's write.js builds."""
    block = json.dumps({"version": 1, "changes": changes, "settings": settings}, separators=(",", ":"))
    return (f"{note + chr(10) + chr(10) if note else ''}Sent from the StackVitals app. The StackVitals workflow applies this when "
            f"someone with access opens it, answers here and closes it.\n\n```stackvitals\n{block}\n```\n")


def proposal(repo: str, settings: dict | None = None, command: str | None = None, note: str = "", today: date | None = None) -> dict:
    """{url, title, note}: a link to a prefilled request issue; ProposalError when the change can't be applied."""
    today = today or datetime.now(timezone.utc).date()
    settings = settings or {}
    try:
        decided = dec.parse_command(command or "", today) if command else []
    except dec.CommandError as exc:
        raise ProposalError(str(exc)) from None
    if command and not decided:
        raise ProposalError("A command starts with /stackvitals, for example: /stackvitals mute test:<id> for 7d because <reason>.")
    if not decided and not settings:
        raise ProposalError("Nothing to propose: give settings to change and/or a /stackvitals command.")
    if settings:
        try:
            apply("", settings)  # every key must exist and every value be one the parser accepts
        except EditError as exc:
            raise ProposalError(str(exc)) from None
    changes = [asdict(d) for d in decided]
    what = ", ".join([*(f"{d.verb} {d.kind} {d.id}" for d in decided), *settings])
    title = f"StackVitals: {what}"[:120]
    url = f"https://github.com/{repo}/issues/new?title={quote(title)}&body={quote(body(changes, settings, note))}"
    if len(url) > URL_MAX:
        raise ProposalError("This change is too long for one link; split it into smaller ones.")
    need = "write" if settings else "triage or write"
    return {"url": url, "title": title,
            "note": f"Open the link and press Submit; the StackVitals workflow applies it when someone with {need} access opened it."}


def _value(text: str):
    try:
        return json.loads(text)
    except ValueError:
        return text  # a plain word, like a regex or a day name


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stackvitals propose",
                                     description="Print a link that proposes a settings change or a decision; a person submits it.")
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                        help="a setting, e.g. alerts.pickup_p75_hours=6 or automation.issues=true (JSON values)")
    parser.add_argument("--decide", help='a command, e.g. "/stackvitals mute test:<id> for 7d because <reason>"')
    parser.add_argument("--note", default="", help="a line of context for the person who submits it")
    args = parser.parse_args(argv)
    settings = {}
    for item in args.set:
        key, sep, value = item.partition("=")
        if not sep:
            print(f"--set needs KEY=VALUE, not {item!r}", file=sys.stderr)
            return 2
        settings[key.strip()] = _value(value.strip())
    try:
        out = proposal(args.repo, settings, args.decide, args.note)
    except ProposalError as exc:
        print(f"Not proposed: {exc}", file=sys.stderr)
        return 1
    print(out["note"])
    print(out["url"])
    return 0
