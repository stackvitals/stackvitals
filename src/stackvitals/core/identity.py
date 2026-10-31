"""One person across tools: [identity] aliases map a GitHub login's old names, and also a tool's id ("jira:<accountId>",
"linear:<id>", "slack:<user id>", "discord:<user id>") or an email, to the login used everywhere else."""
import re


def _aliases(ident: dict | None) -> dict[str, str]:
    return {k.lower(): v for k, v in ((ident or {}).get("aliases") or {}).items()}


def login(ident: dict | None, ref: str | None, email: str | None = None) -> str | None:
    """The GitHub login a tool's id or an email belongs to; None when no alias names it."""
    aliases = _aliases(ident)
    for key in (ref, email):
        if key and key.lower() in aliases:
            return aliases[key.lower()]
    return None


def team_of(ident: dict | None, who: str | None) -> list[str]:
    """The teams in the identity settings that list this login."""
    low = (who or "").lower()
    return [team for team, logins in ((ident or {}).get("teams") or {}).items() if low and low in {x.lower() for x in logins}]


def tool_ids(ident: dict | None, tool: str) -> set[str]:
    """A chat tool's user ids that map to a team member or a listed person, so the team is never listed twice."""
    members = {x.lower() for logins in ((ident or {}).get("teams") or {}).values() for x in logins}
    members |= {x.lower() for x in (ident or {}).get("people") or []}
    prefix = tool + ":"
    return {k[len(prefix):] for k, v in ((ident or {}).get("aliases") or {}).items()
            if k.lower().startswith(prefix) and v.lower() in members}


def _plain(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def match(ident: dict | None, ref: str | None, email: str | None, name: str | None, logins: set[str]) -> tuple:
    """(login, confidence) for a tool's user: "alias" from the settings, "high" when the email's name part is a login
    (GitHub's noreply address too), "medium" when the email or display name only reads like one login; else (None, None)."""
    if who := login(ident, ref, email):
        return who, "alias"
    by_low = {x.lower(): x for x in logins}
    local = (email or "").split("@")[0].lower()
    if "@users.noreply.github.com" in (email or "").lower():
        local = local.split("+")[-1]
    if local in by_low:
        return by_low[local], "high"
    by_plain = {}
    for x in logins:
        by_plain.setdefault(_plain(x), []).append(x)
    for key in (_plain(local), _plain(name or "")):
        if key and len(by_plain.get(key, [])) == 1:
            return by_plain[key][0], "medium"
    return None, None


def issues_by_team(issues: list[dict], ident: dict | None, since: str, logins: set[str] | None = None) -> dict:
    """Tracker issues done since `since`, counted for each team of the person they were assigned to; plus how many done
    issues had an assignee that no alias names. With the repo's logins, an email that is a login counts too, and a
    name that only looks like one is suggested as an alias line to paste (never counted)."""
    teams, matched, unmatched, by_email, guesses = {}, 0, 0, 0, {}
    for i in issues:
        if i.get("cat") != "DONE" or (i.get("resolved") or "") < since or not i.get("assignee"):
            continue
        who, sure = match(ident, i["assignee"], i.get("assignee_email"), i.get("assignee_name"), logins or set())
        if sure == "medium":
            guesses.setdefault((i["assignee"], who), 0)
            guesses[(i["assignee"], who)] += 1
        if sure not in ("alias", "high"):
            unmatched += 1
            continue
        matched += 1
        by_email += sure == "high"
        for team in team_of(ident, who):
            teams.setdefault(team, {"done": 0})["done"] += 1
    out = {"teams": teams, "matched": matched, "unmatched": unmatched}
    if logins is not None:
        out["by_email"] = by_email
        out["suggested"] = [{"ref": ref, "login": who, "issues": n, "line": f'"{ref}" = "{who}"'}
                            for (ref, who), n in sorted(guesses.items(), key=lambda kv: -kv[1])][:20]
    return out
