"""Verified self-healing CI: a failure that breaks the default branch every run (not a flake) gets one fix request, an
issue with the evidence an agent or a person needs and a definition of done; StackVitals closes it with proof once the
tests pass there again, and reopens it if they break again. It never pushes code: a fix is someone's pull request."""
import re

from stackvitals.ci.api import APIError
from stackvitals.ci.investigate import prompt

LABEL = "stackvitals-fix"
NEW_PER_RUN = 2  # fix requests opened in one run; the rest wait for the next
COPILOT = "copilot-swe-agent[bot]"  # GitHub's coding agent, when the team turns on fix_by_copilot
MARK = re.compile(r"<!-- stackvitals-fix:(\S+) tests=([^>]*?) -->")


def _title(g: dict) -> str:
    return f"CI broken: {g.get('type') or 'failure'} at {g.get('where') or 'an unknown place'}"[:200]


def _broken(result: dict) -> list[tuple[dict, list[str]]]:
    """Failure groups whose tests fail every recent run on the default branch, with those tests (muted ones left out)."""
    state = {t["id"]: t for t in result.get("tests") or []}
    out = []
    for g in result.get("failure_groups") or []:
        hit = [tid for tid in g.get("top_tests") or [] if (state.get(tid) or {}).get("state") == "broken"
               and not state[tid].get("muted_until")]
        if hit:
            out.append((g, hit))
    return out


def _body(repo: str, g: dict, tests: list[str], result: dict, branch: str) -> str:
    done = "\n".join(f"- `{t}`" for t in tests)
    return "\n".join([
        prompt(repo, g, result.get("tests") or []),
        "",
        f"**Done when** these tests pass on {branch} again; StackVitals then closes this issue with the runs that show it:",
        done,
        "",
        "Opened by StackVitals because these tests fail every recent run on the default branch (not a flake). StackVitals "
        "never pushes code: a fix is a pull request someone (or a coding agent assigned here) opens and a person merges.",
        f"<!-- stackvitals-fix:{g['id']} tests={','.join(tests)} -->",
    ])


def _all(api) -> dict[str, dict]:
    found = {}
    for page in range(1, 4):
        batch = api._get(f"/repos/{api.repo}/issues", {"labels": LABEL, "state": "all", "per_page": 100, "page": page}) or []
        for issue in batch:
            m = MARK.search(issue.get("body") or "")
            if "pull_request" not in issue and m and issue["number"] > found.get(m.group(1), {}).get("number", 0):
                found[m.group(1)] = {**issue, "_tests": [t for t in m.group(2).split(",") if t]}
        if len(batch) < 100:
            break
    return found


def sync_fix_requests(api, result: dict, assign: str | None = None, branch: str | None = None) -> dict:
    """Open, update, verify-and-close and reopen fix requests; `assign="copilot"` also assigns GitHub's coding agent."""
    branch = branch or result.get("default_branch") or "the default branch"
    issues = _all(api)
    counts = {"created": 0, "updated": 0, "verified": 0, "reopened": 0, "kept_closed": 0, "assigned": 0, "held": 0}
    broken = _broken(result)
    for g, tests in broken:
        issue, body = issues.get(g["id"]), _body(api.repo, g, tests, result, branch)
        if issue and issue.get("state") == "open":
            api.send("PATCH", f"/repos/{api.repo}/issues/{issue['number']}", {"body": body})
            counts["updated"] += 1
        elif issue and issue.get("state_reason") not in (None, "completed", "reopened"):
            counts["kept_closed"] += 1  # the team decided not to fix it here
        elif issue:
            api.send("PATCH", f"/repos/{api.repo}/issues/{issue['number']}", {"state": "open", "body": body})
            api.send("POST", f"/repos/{api.repo}/issues/{issue['number']}/comments",
                     {"body": f"Broken again on {branch}: {', '.join(f'`{t}`' for t in tests)} fail every recent run."})
            counts["reopened"] += 1
        elif counts["created"] >= NEW_PER_RUN:
            counts["held"] += 1
        else:
            new = {"title": _title(g), "body": body, "labels": [LABEL]}
            if assign == "copilot":
                try:
                    api.send("POST", f"/repos/{api.repo}/issues", {**new, "assignees": [COPILOT]})
                    counts["assigned"] += 1
                except APIError:
                    # The agent isn't enabled here, or the token can't assign it: the request still stands.
                    api.send("POST", f"/repos/{api.repo}/issues", new)
            else:
                api.send("POST", f"/repos/{api.repo}/issues", new)
            counts["created"] += 1
    still = {g["id"] for g, _t in broken}
    state = {t["id"]: t.get("state") for t in result.get("tests") or []}
    for gid, issue in issues.items():
        if issue.get("state") != "open" or gid in still or not issue["_tests"]:
            continue
        # Verified only when every test it named is measured again and none is broken or flaky.
        if all(state.get(t) not in (None, "broken", "flaky", "suspect") for t in issue["_tests"]):
            api.send("POST", f"/repos/{api.repo}/issues/{issue['number']}/comments",
                     {"body": f"Fixed: {', '.join(f'`{t}`' for t in issue['_tests'])} pass again on {branch} in the latest "
                              "runs StackVitals read. Closing; it reopens if they break again."})
            api.send("PATCH", f"/repos/{api.repo}/issues/{issue['number']}", {"state": "closed", "state_reason": "completed"})
            counts["verified"] += 1
    return counts
