"""Who is a person, a bot or a coding agent, and who is an insider: one rule for every module, the crawl's rule
(`mergescout.signals.identity`), so a repo's own numbers and its peer benchmarks mean the same thing."""
import re
from collections import defaultdict
from dataclasses import dataclass

from mergescout.signals.rules import (AI_AGENT_BOT_NAMES, AI_AGENT_LOGINS, BOT_NAME_PATTERN, HUMAN_BOT_NAMES,
                                      KNOWN_BOTS, UNKNOWN_LOGINS)

INSIDER_ASSOC = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})
_BOT_NAME = re.compile(BOT_NAME_PATTERN)
_HUMAN_NAME = re.compile(HUMAN_BOT_NAMES)
# The crawl's reason order, so both sides print the same text.
REASONS = ("bot account", "listed role", "merges others", "merges own", "in owner files")


def kind_of(login: str | None, typ: str | None = None) -> str:
    """person, bot, agent or unknown, from the login and GitHub's account type when known."""
    if not login or login.lower() in UNKNOWN_LOGINS:
        return "unknown"
    if typ == "Person":  # set by a repo's identity settings, so it beats the name rules
        return "person"
    low = login.lower()
    base = low.removesuffix("[bot]")
    bot = typ == "Bot" or low.endswith("[bot]") or low in KNOWN_BOTS or bool(_BOT_NAME.search(low) and not _HUMAN_NAME.search(low))
    if base in AI_AGENT_LOGINS or (base in AI_AGENT_BOT_NAMES and bot):
        return "agent"
    return "bot" if bot else "person"


@dataclass(frozen=True)
class Actor:
    login: str
    kind: str  # person, bot, agent, unknown
    role: str  # insider, outsider, or the kind again for non-people
    reasons: tuple[str, ...]


class People:
    """Insiders are found by what they do: a listed role anywhere, merging anyone's PR, or a name in the owner files."""

    def __init__(self, prs: list[dict], issues: list[dict] = (), owner_logins: list[str] = ()):
        self._typ: dict[str, str | None] = {}
        self._name: dict[str, str] = {}
        self._flags: dict[str, set[str]] = defaultdict(set)
        for r in list(prs) + list(issues):
            au = r.get("au")
            self._see(au, r.get("at"), r.get("as"))
            for e in r.get("ev") or []:
                if e[0] == "review" and len(e) > 5:
                    self._see(e[2], e[5], e[4])
                elif e[0] == "merged" and len(e) > 2 and e[2]:
                    self._see(e[2], None, None)
                    self._flags[e[2].lower()].add("merges own" if e[2] == au else "merges others")
            for c in r.get("cm") or []:
                if len(c) > 3:
                    self._see(c[1], c[3], c[2])
        for login in owner_logins:
            if login:
                self._see(login, None, None)
                self._flags[login.lower()].add("in owner files")

    def _see(self, login: str | None, typ: str | None, assoc: str | None) -> None:
        if not login:
            return
        low = login.lower()
        self._name.setdefault(low, login)
        # Once seen as a bot account, always a bot.
        if typ == "Bot" or self._typ.get(low) is None:
            self._typ[low] = typ or self._typ.get(low)
        if assoc in INSIDER_ASSOC:
            self._flags[low].add("listed role")

    def kind(self, login: str | None) -> str:
        return kind_of(login, self._typ.get((login or "").lower()))

    def role(self, login: str | None) -> str:
        kind = self.kind(login)
        if kind != "person":
            return kind
        return "insider" if self._flags.get(login.lower()) else "outsider"

    def reasons(self, login: str | None) -> str:
        if not login:
            return ""
        found = self._flags.get(login.lower(), set())
        if self.kind(login) in ("bot", "agent"):
            found = found | {"bot account"}
        return ", ".join(r for r in REASONS if r in found)

    def actor(self, login: str | None) -> Actor:
        return Actor(login or "", self.kind(login), self.role(login), tuple(r for r in REASONS if r in self._flags.get((login or "").lower(), ())))

    def is_insider(self, login: str | None) -> bool:
        return self.role(login) == "insider"

    def insiders(self) -> set[str]:
        return {self._name[low] for low in self._flags if self.role(self._name[low]) == "insider"}

    def is_outside(self, rec: dict) -> bool:
        """A person who is not an insider wrote it: never a bot, an agent, a ghost or a maintainer."""
        au = rec.get("au")
        return kind_of(au, rec.get("at")) == "person" and self.role(au) == "outsider"
