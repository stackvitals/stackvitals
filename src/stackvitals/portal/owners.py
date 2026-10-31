"""Who owns a repo, checked rather than just read: the CODEOWNERS file GitHub would use, GitHub's own error check, teams that
have members, and users who are still in the org. Without a file, recent committers are offered as suggestions only."""
from collections import Counter
from datetime import datetime, timedelta

from stackvitals import codeowners
from stackvitals.portal.github import NA, read, read_file, status

# Commit authors that are not people: GitHub's placeholder for unlinked emails, web edits, deleted accounts.
PLACEHOLDERS = {"invalid-email-address", "web-flow", "ghost"}
CATCH_ALL = {"*", "/*", "/", "**", "/**"}
CODEOWNERS_PATHS = codeowners.PATHS
MAX_USER_CHECKS = 10


parse_codeowners = codeowners.parse


def suggest(api, repo: str, now: datetime, days: int = 90) -> list[str]:
    commits = read(api, f"/repos/{repo}/commits", {"since": (now - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                   "per_page": 100})
    if commits is NA or not isinstance(commits, list):
        return []
    counts = Counter(((c.get("author") or {}).get("login") for c in commits))
    # Machine accounts are often plain users named like bots (zaniebot, astral-docs-bot): never suggested as owners.
    return [who for who, _ in counts.most_common()
            if who and who.lower() not in PLACEHOLDERS and not who.lower().endswith(("bot", "[bot]", "-bot"))][:3]


def owner_status(api, org: str, repo: dict, now: datetime, cache: dict, members_visible: bool = True,
                 reviewers: list[str] | None = None, pre: dict | None = None) -> dict:
    """valid / weak / none, with the reasons. Team sizes and memberships are cached for the whole run. In public mode
    the token can't see private memberships, so users aren't checked (members_visible=False)."""
    name, branch = repo["name"], repo.get("default_branch")
    text = file = None
    if pre:
        file, text = pre["codeowners"]
    for path in () if pre else CODEOWNERS_PATHS:
        got = read_file(api, name, path, branch)
        if got is not NA:
            text, file = got, path
            break
    if text is None:
        # People who review are better owner candidates than committers (machine accounts commit, e.g. charmcli).
        return {"status": "none", "file": None, "reasons": ["no CODEOWNERS file"], "owners": [], "teams": {}, "notes": [],
                "suggested": (reviewers or [])[:3] or suggest(api, name, now),
                "suggested_from": "recent reviews" if reviewers else "recent commits"}
    rules = parse_codeowners(text)
    owners = sorted({o for _, os in rules for o in os})
    reasons, teams, notes = [], {}, []
    if not any(pattern in CATCH_ALL and os for pattern, os in rules):
        reasons.append("no catch-all line (* or /): files outside the listed paths have no owner")
    errors = read(api, f"/repos/{name}/codeowners/errors", {"ref": branch} if branch else None)
    if errors is not NA and (errors or {}).get("errors"):
        reasons.append(f"{len(errors['errors'])} errors in CODEOWNERS (GitHub's own check)")
    users = 0
    for owner in owners:
        if owner.startswith("@") and "/" in owner:
            team = owner[1:]
            team_org, slug = team.split("/", 1)
            if ("team", team) not in cache:
                members = read(api, f"/orgs/{team_org}/teams/{slug}/members", {"per_page": 100})
                cache[("team", team)] = NA if members is NA else len(members)
            teams[team] = cache[("team", team)]
            if teams[team] == 0:
                reasons.append(f"team {team} has no members")
        elif owner.startswith("@") and members_visible and users < MAX_USER_CHECKS:
            user, users = owner[1:], users + 1
            if ("member", user) not in cache:
                cache[("member", user)] = status(api, f"/orgs/{org}/members/{user}")
            if cache[("member", user)] == 404:
                reasons.append(f"{user} is named as an owner but is not a member of {org}")
    if any(v is NA for v in teams.values()):
        notes.append("team members not visible to this token")
    if not members_visible and any(o.startswith("@") and "/" not in o for o in owners):
        notes.append("org membership of named users not checked (not visible to this token)")
    return {"status": "weak" if reasons else "valid", "file": file, "reasons": reasons, "owners": owners, "notes": notes,
            "teams": {k: (None if v is NA else v) for k, v in teams.items()}}
