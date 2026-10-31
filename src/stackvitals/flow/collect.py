import re
from collections import defaultdict
from datetime import datetime, timedelta

from mergescout.github.graphql import GraphQLError, RateLimited, too_heavy
from stackvitals.flow.store import FlowStore

# One page of PRs with their review history costs about 1 point per 25 PRs (measured on poetry and vite).
QUERY = """
query($owner:String!,$name:String!,$cursor:String,$n:Int!) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner,name:$name) {
    pullRequests(first:$n, after:$cursor, orderBy:{field:UPDATED_AT, direction:DESC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number title body isDraft state mergeable createdAt updatedAt mergedAt closedAt additions deletions changedFiles
        author { __typename login } authorAssociation baseRefName headRefName headRepositoryOwner { login }
        files(first:50) { nodes { path } }
        closingIssuesReferences(first:1) { totalCount }
        commits(last:1) { nodes { commit { committedDate authoredDate statusCheckRollup { state } } } }
        first: commits(first:1) { totalCount nodes { commit { authoredDate } } }
        mergeCommit { oid }
        early: timelineItems(first:5, itemTypes:[ISSUE_COMMENT]) {
          nodes { ... on IssueComment { createdAt author { __typename login } authorAssociation } } }
        reviewRequests(first:10) { nodes { requestedReviewer { __typename ... on User { login } ... on Team { slug } } } }
        events: timelineItems(first:60, itemTypes:[READY_FOR_REVIEW_EVENT, CONVERT_TO_DRAFT_EVENT, REVIEW_REQUESTED_EVENT,
              REVIEW_REQUEST_REMOVED_EVENT, PULL_REQUEST_REVIEW, MERGED_EVENT, CLOSED_EVENT, REOPENED_EVENT]) {
          filteredCount
          nodes { __typename
            ... on ReadyForReviewEvent { createdAt }
            ... on ConvertToDraftEvent { createdAt }
            ... on ReviewRequestedEvent { createdAt requestedReviewer { __typename ... on User { login } ... on Team { slug } } }
            ... on ReviewRequestRemovedEvent { createdAt requestedReviewer { __typename ... on User { login } ... on Team { slug } } }
            ... on PullRequestReview { submittedAt state author { __typename login } authorAssociation body comments { totalCount } }
            ... on MergedEvent { createdAt actor { login } }
            ... on ClosedEvent { createdAt actor { login } }
            ... on ReopenedEvent { createdAt }
          }
        }
        labels(first:20) { nodes { name } }
        marks: timelineItems(last:20, itemTypes:[LABELED_EVENT, UNLABELED_EVENT, ASSIGNED_EVENT, UNASSIGNED_EVENT]) {
          nodes { __typename ... on LabeledEvent { createdAt label { name } } ... on UnlabeledEvent { createdAt label { name } }
            ... on AssignedEvent { createdAt assignee { __typename ... on User { login } } }
            ... on UnassignedEvent { createdAt assignee { __typename ... on User { login } } } }
        }
        queue: timelineItems(last:10, itemTypes:[ADDED_TO_MERGE_QUEUE_EVENT, REMOVED_FROM_MERGE_QUEUE_EVENT]) {
          nodes { __typename ... on AddedToMergeQueueEvent { createdAt } ... on RemovedFromMergeQueueEvent { createdAt reason } } }
        recent: commits(last:5) { nodes { commit { authoredDate committedDate parents { totalCount } author { user { login } } message } } }
        talk: timelineItems(last:10, itemTypes:[ISSUE_COMMENT]) {
          filteredCount nodes { ... on IssueComment { createdAt body author { __typename login } authorAssociation } }
        }
      }
    }
  }
}"""

# Without checks/statuses read access the built-in token may not read a commit's check result; ask without it then.
QUERY_NO_CHECKS = QUERY.replace(" statusCheckRollup { state }", "")
# Once per run: where code ships (releases, deployments), the default branch and CODEOWNERS (1 point).
REPO_QUERY = """
query($owner:String!,$name:String!) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner,name:$name) {
    defaultBranchRef { name }
    primaryLanguage { name }
    stargazerCount
    isPrivate
    releases(first:100, orderBy:{field:CREATED_AT, direction:DESC}) {
      nodes { tagName createdAt publishedAt isPrerelease isDraft tagCommit { oid } } }
    deployments(first:100, orderBy:{field:CREATED_AT, direction:DESC}) {
      nodes { environment createdAt commitOid latestStatus { state createdAt } } pageInfo { hasNextPage endCursor } }
    co1: object(expression:"HEAD:.github/CODEOWNERS") { ... on Blob { text } }
    co2: object(expression:"HEAD:CODEOWNERS") { ... on Blob { text } }
    co3: object(expression:"HEAD:docs/CODEOWNERS") { ... on Blob { text } }
  }
}"""
# Deployments past the newest 100 (previews crowd out production on busy repos), one point a page.
DEPLOY_PAGE = """
query($owner:String!,$name:String!,$after:String) {
  rateLimit { cost remaining resetAt }
  repository(owner:$owner,name:$name) {
    deployments(first:100, after:$after, orderBy:{field:CREATED_AT, direction:DESC}) {
      nodes { environment createdAt commitOid latestStatus { state createdAt } } pageInfo { hasNextPage endCursor } }
  }
}"""
MAX_DEPLOY_PAGES = 40
# The commits each production deployment shipped: its history back to the deployment before it, 20 per query.
RANGE_OID = re.compile(r'object\(oid:"([0-9a-z]+)"\)')
RANGE_BATCH = 20
# The built-in token reads deployments only with `deployments: read` (every sandbox run failed without it): ask without them.
REPO_QUERY_NO_DEPLOYMENTS = REPO_QUERY.replace("""    deployments(first:100, orderBy:{field:CREATED_AT, direction:DESC}) {
      nodes { environment createdAt commitOid latestStatus { state createdAt } } pageInfo { hasNextPage endCursor } }
""", "")
# Records saved before file lists, linked issues, conflicts, authored dates, review flags, labels, commit authors and assignees
# were collected are read again once.
SCHEMA = 8
OVERLAP = timedelta(hours=1)
OPEN_ONLY = ("lbe", "cmt", "asg")
SIMPLE = {"ReadyForReviewEvent": "ready", "ConvertToDraftEvent": "draft", "ClosedEvent": "closed",
          "ReopenedEvent": "reopened"}


def _who(reviewer: dict | None) -> str | None:
    if not reviewer:
        return None
    if reviewer.get("__typename") == "Team":
        return f"team:{reviewer.get('slug')}"
    return reviewer.get("login")


def _event(e: dict, pr_author: str | None = None) -> list | None:
    kind = e.get("__typename")
    if kind == "ClosedEvent":
        # Who closed it: an author closing their own PR is not an answer (Community).
        return ["closed", e.get("createdAt"), (e.get("actor") or {}).get("login")]
    if kind in SIMPLE:
        return [SIMPLE[kind], e.get("createdAt")]
    if kind == "ReviewRequestedEvent":
        return ["req", e.get("createdAt"), _who(e.get("requestedReviewer"))]
    if kind == "ReviewRequestRemovedEvent":
        return ["unreq", e.get("createdAt"), _who(e.get("requestedReviewer"))]
    if kind == "PullRequestReview":
        author = e.get("author") or {}
        # Whether the review raised something (line comments, a question, a mention); its text is never kept.
        raised = bool((e.get("comments") or {}).get("totalCount")) or _asks_author(e.get("body"), pr_author)
        return ["review", e.get("submittedAt"), author.get("login"), e.get("state"), e.get("authorAssociation"),
                author.get("__typename"), raised]
    if kind == "MergedEvent":
        return ["merged", e.get("createdAt"), (e.get("actor") or {}).get("login")]
    return None


# Co-author trailers and footers coding assistants add to commits: what a public repo can show about AI help.
AI_TRAILERS = (("claude", ("noreply@anthropic.com", "co-authored-by: claude", "generated with [claude code]")),
               ("copilot", ("copilot@users.noreply.github.com", "co-authored-by: copilot")),
               ("cursor", ("cursoragent@cursor.com", "co-authored-by: cursor")),
               ("codex", ("co-authored-by: codex", "codex@openai.com")),
               ("devin", ("devin-ai-integration",)),
               ("aider", ("co-authored-by: aider",)),
               ("gemini", ("co-authored-by: gemini",)))


def ai_tools(messages) -> list[str]:
    text = "\n".join(m or "" for m in messages).lower()
    return sorted(name for name, marks in AI_TRAILERS if any(m in text for m in marks))


# Links a coding agent leaves in the PR description it wrote (a Codex task, a Devin session, a Cursor agent).
BODY_MARKS = (("codex", ("chatgpt.com/codex/tasks/",)), ("devin", ("app.devin.ai/sessions/",)),
              ("cursor", ("cursor.com/background-agent", "cursor.com/agents")), ("jules", ("jules.google.com/task",)))


def body_tools(body: str | None) -> list[str]:
    """AI tools a PR's description names: the commit trailers and footers, or an agent's task link."""
    text = (body or "").lower()
    return sorted(set(ai_tools([text])) | {name for name, marks in BODY_MARKS if any(m in text for m in marks)})


def _asks_author(body: str | None, author: str | None) -> bool:
    text = body or ""
    return "?" in text or bool(author and f"@{author.lower()}" in text.lower())


def _assignees(marks: list[dict]) -> list[str]:
    # Who is assigned now, replayed from the last assignment events (a separate assignees list costs a point more per page).
    current = []
    for x in sorted((m for m in marks if m and m.get("createdAt")), key=lambda m: m["createdAt"]):
        who = (x.get("assignee") or {}).get("login")
        if who and x.get("__typename") == "AssignedEvent" and who not in current:
            current.append(who)
        elif who and x.get("__typename") == "UnassignedEvent" and who in current:
            current.remove(who)
    return current


def pr_record(node: dict, now: datetime) -> dict:
    """One PR as a compact record: its state, size, author, open review requests and timed events."""
    author = node.get("author") or {}
    last = ((node.get("commits") or {}).get("nodes") or [{}])[-1].get("commit") or {}
    events = [ev for e in (node.get("events") or {}).get("nodes") or [] if e and (ev := _event(e, author.get("login"))) and ev[1]]
    # Comment text is only used to tell whether it asks the author something; it is never kept.
    talk = [[c.get("createdAt"), (c.get("author") or {}).get("login"), c.get("authorAssociation"),
             (c.get("author") or {}).get("__typename"), _asks_author(c.get("body"), author.get("login"))]
            for c in (node.get("talk") or {}).get("nodes") or [] if c]
    # The first comments too: pickup ends at the first answer, which the latest ten miss on busy PRs (no text read).
    seen = {(c[0], c[1]) for c in talk}
    talk += [[c.get("createdAt"), (c.get("author") or {}).get("login"), c.get("authorAssociation"),
              (c.get("author") or {}).get("__typename"), False]
             for c in (node.get("early") or {}).get("nodes") or []
             if c and c.get("createdAt") and (c.get("createdAt"), (c.get("author") or {}).get("login")) not in seen]
    first = node.get("first") or {}
    recent = [x.get("commit") or {} for x in (node.get("recent") or {}).get("nodes") or [] if x]
    return {"t": "pr", "n": node["number"], "ti": (node.get("title") or "")[:200], "draft": node.get("isDraft"), "st": node.get("state"),
            "cr": node.get("createdAt"), "up": node.get("updatedAt"), "mg": node.get("mergedAt"), "cl": node.get("closedAt"),
            "add": node.get("additions"), "del": node.get("deletions"), "files": node.get("changedFiles"),
            "au": author.get("login"), "at": author.get("__typename"), "as": node.get("authorAssociation"),
            "base": node.get("baseRefName"), "head": node.get("headRefName"),
            "ho": (node.get("headRepositoryOwner") or {}).get("login"),
            "lc": last.get("committedDate"), "la": last.get("authoredDate"), "mgs": node.get("mergeable"), "ci": (last.get("statusCheckRollup") or {}).get("state"),
            "iss": bool(((node.get("closingIssuesReferences") or {}).get("totalCount") or 0)),
            "paths": [f["path"] for f in (node.get("files") or {}).get("nodes") or [] if f and f.get("path")],
            "rq": [w for r in (node.get("reviewRequests") or {}).get("nodes") or [] if (w := _who((r or {}).get("requestedReviewer")))],
            "ev": sorted(events, key=lambda e: e[1]), "evn": (node.get("events") or {}).get("filteredCount"),
            # When it entered and left a merge queue, and why it left (merge-queue health); only on PRs that used one.
            **({"mq": queue} if (queue := [["add", q.get("createdAt")] if q.get("__typename") == "AddedToMergeQueueEvent"
                                          else ["rm", q.get("createdAt"), q.get("reason")]
                                          for q in (node.get("queue") or {}).get("nodes") or [] if q and q.get("createdAt")]) else {}),
            "cm": sorted((c for c in talk if c[0]), key=lambda c: c[0]),
            "cmn": (node.get("talk") or {}).get("filteredCount"),
            "fa": ((((first.get("nodes") or [{}])[0] or {}).get("commit") or {}).get("authoredDate")),
            "nc": first.get("totalCount"), "mc": (node.get("mergeCommit") or {}).get("oid"),
            # Only the tools named are kept, never the description itself.
            "ai": sorted(set(ai_tools(c.get("message") for c in recent)) | set(body_tools(node.get("body")))),
            "lb": [x["name"] for x in (node.get("labels") or {}).get("nodes") or [] if x and x.get("name")],
            "asg": _assignees((node.get("marks") or {}).get("nodes") or []),
            # When labels were added (+) or removed (-), and who made the last commits (a maintainer's merge of main isn't the author's work).
            "lbe": [[x.get("createdAt"), "+" if x.get("__typename") == "LabeledEvent" else "-", (x.get("label") or {}).get("name")]
                    for x in (node.get("marks") or {}).get("nodes") or []
                    if x and x.get("createdAt") and x.get("__typename") in ("LabeledEvent", "UnlabeledEvent")],
            "cmt": [[c.get("authoredDate"), c.get("committedDate"), ((c.get("author") or {}).get("user") or {}).get("login"),
                     ((c.get("parents") or {}).get("totalCount") or 0) > 1]
                    for c in (x.get("commit") or {} for x in (node.get("recent") or {}).get("nodes") or [] if x)],
            "f": now.strftime("%Y-%m-%dT%H:%M:%SZ")}


def collect(gql, store: FlowStore, owner: str, name: str, now: datetime, months: int = 12, page: int = 25,
            max_pages: int = 500, log=None) -> dict:
    """Read PRs updated since the last run (or the last `months` on the first), newest first."""
    state = store.state()
    synced = state.get("synced_up_to") if state.get("schema", 1) >= SCHEMA else None
    floor = (datetime.fromisoformat(synced.replace("Z", "+00:00")) - OVERLAP if synced
             else now - timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%SZ")
    opened, closed = store.open(), defaultdict(list)
    cursor, newest, count, cost, complete, pages = None, None, 0, 0, True, 0
    query, no_checks = QUERY, False
    while pages < max_pages:
        try:
            result = gql.query(query, {"owner": owner, "name": name, "cursor": cursor, "n": page})
        except RateLimited:
            complete = False
            break
        except GraphQLError as exc:
            if "not accessible" in str(exc).lower() and query is QUERY:
                query, no_checks = QUERY_NO_CHECKS, True
                continue
            # A page GitHub finds too heavy is asked again in smaller pieces.
            if too_heavy(exc) and page > 5:
                page = max(5, page // 2)
                continue
            raise
        pages += 1
        cost += result.cost
        block = result.data["repository"]["pullRequests"]
        stop = False
        for node in block["nodes"]:
            if not node:
                continue
            if node["updatedAt"] < floor:
                stop = True
                break
            newest = newest or node["updatedAt"]
            rec = pr_record(node, now)
            count += 1
            if rec["st"] == "OPEN":
                opened[rec["n"]] = rec
            else:
                opened.pop(rec["n"], None)
                # Labels, label times and commit authors only matter while a PR is open (history stays ~20% smaller).
                closed[(rec["cl"] or rec["up"])[:10]].append({k: v for k, v in rec.items() if k not in OPEN_ONLY})
        if log and pages % 20 == 0:
            log(f"{count} PRs read so far ({cost} points)")
        if stop or not block["pageInfo"]["hasNextPage"]:
            break
        cursor = block["pageInfo"]["endCursor"]
    else:
        complete = False
    for day, recs in closed.items():
        store.put(recs, day)
    store.save_open(opened)
    if complete:
        state["synced_up_to"] = max(filter(None, [newest, synced]), default=None)
        state["schema"] = SCHEMA
    info = repo_info(gql, owner, name, (now - timedelta(days=30 * months)).strftime("%Y-%m-%dT%H:%M:%SZ"), store.repo())
    # A refused repo query keeps the details an earlier run saved.
    if "default_branch" in info:
        store.save_repo(info)
    # Which failing checks are required, and whether CI waits for approval (open PRs only).
    collect_checks(gql, store, owner, name)
    state["last_collect"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    store.save_state(state)
    store.compress(now.date().isoformat())
    return {"prs": count, "points": cost, "complete": complete, "no_checks": no_checks,
            "no_deployments": bool(info.get("no_deployments"))}


def repo_info(gql, owner: str, name: str, since: str | None = None, saved: dict | None = None) -> dict:
    """Releases (drafts left out), deployments, the default branch and CODEOWNERS text. Repo details are extras: a
    refused query is asked again without deployments, and if that fails too the run goes on without them."""
    no_deployments = False
    try:
        repo = gql.query(REPO_QUERY, {"owner": owner, "name": name}).data["repository"]
    except GraphQLError:
        no_deployments = True
        try:
            repo = gql.query(REPO_QUERY_NO_DEPLOYMENTS, {"owner": owner, "name": name}).data["repository"]
        except GraphQLError:
            return {"no_deployments": True}
    complete = False
    if not no_deployments and since and repo.get("deployments"):
        more, complete = _older_deployments(gql, owner, name, repo["deployments"], since, saved)
        repo["deployments"]["nodes"] += more
    info = _repo_fields(repo)
    if since and not no_deployments:
        info["deployments"] = merge_history((saved or {}).get("deployments") or [], info["deployments"], since)
        # How far back the saved deployments are complete; a capped backfill goes on next run.
        if complete or ((saved or {}).get("deployments_from") or "9") <= since:
            info["deployments_from"] = since
    if since and not no_deployments:
        info["ranges"] = deploy_ranges(gql, owner, name, info["deployments"], (saved or {}).get("ranges") or {})
    if since:
        info["releases"] = merge_history((saved or {}).get("releases") or [], info["releases"], since, ("tag",))
    return {**info, "no_deployments": True} if no_deployments else info


def _older_deployments(gql, owner: str, name: str, block: dict, since: str, saved: dict | None) -> list[dict]:
    """Pages past the newest 100, back to the window or to two days before what an earlier run saved."""
    known = [d["at"] for d in (saved or {}).get("deployments") or [] if d.get("at")]
    # Saved history counts only once it is complete back to the window (older saves kept just the newest 100).
    complete = known and ((saved or {}).get("deployments_from") or "9") <= since
    stop = max([since] + ([(datetime.fromisoformat(max(known).replace("Z", "+00:00")) - timedelta(days=2))
                           .strftime("%Y-%m-%dT%H:%M:%SZ")] if complete else []))
    out, pages = [], 0
    while True:
        oldest = min((n["createdAt"] for n in block.get("nodes") or [] if n and n.get("createdAt")), default="")
        if oldest < stop or not (block.get("pageInfo") or {}).get("hasNextPage"):
            block["complete"] = True
            break
        if pages >= MAX_DEPLOY_PAGES:
            break
        try:
            block = gql.query(DEPLOY_PAGE, {"owner": owner, "name": name, "after": block["pageInfo"]["endCursor"]}
                              ).data["repository"]["deployments"]
        except GraphQLError:
            break
        out += [n for n in block.get("nodes") or [] if n and (n.get("createdAt") or "") >= since]
        pages += 1
    return out, bool(block.get("complete"))


def deploy_ranges(gql, owner: str, name: str, deployments: list[dict], saved: dict) -> dict:
    """{"prev..sha": {"shas": [...], "complete": bool}} for each pair of successive production deployments: the
    commits the newer one shipped, newest first (incomplete when the older one is over 100 commits back). Pairs read
    before are kept, never read again."""
    from stackvitals.core.config import DELIVERY
    from stackvitals.core.delivery import is_production
    prod = {x.lower() for x in DELIVERY["production"]}
    seq = [d["sha"] for d in sorted((d for d in deployments if d.get("sha") and RANGE_OID.fullmatch(f'object(oid:"{d["sha"]}")')
                                     and d.get("state") in ("SUCCESS", "INACTIVE") and is_production(d.get("env"), prod)),
                                    key=lambda d: d.get("done") or d.get("at") or "")]
    pairs = [(a, b) for a, b in zip(seq, seq[1:]) if a != b]
    out = {f"{a}..{b}": saved[f"{a}..{b}"] for a, b in pairs if f"{a}..{b}" in saved}
    todo = [(a, b) for a, b in pairs if f"{a}..{b}" not in out]
    for i in range(0, len(todo), RANGE_BATCH):
        batch = todo[i:i + RANGE_BATCH]
        parts = " ".join(f'd{k}: object(oid:"{b}") {{ ... on Commit {{ history(first:100) {{ nodes {{ oid }} }} }} }}'
                         for k, (_a, b) in enumerate(batch))
        q = ("query($owner:String!,$name:String!) { rateLimit { cost remaining resetAt } "
             f"repository(owner:$owner,name:$name) {{ {parts} }} }}")
        try:
            repo = gql.query(q, {"owner": owner, "name": name}).data["repository"]
        except GraphQLError:
            break
        for k, (a, b) in enumerate(batch):
            nodes = [n["oid"] for n in ((repo.get(f"d{k}") or {}).get("history") or {}).get("nodes") or [] if n]
            shas = []
            for oid in nodes:
                if oid == a:
                    break
                shas.append(oid)
            out[f"{a}..{b}"] = {"shas": shas, "complete": a in nodes}
    return out


def merge_history(old: list[dict], new: list[dict], keep_since: str, key=("env", "at", "sha")) -> list[dict]:
    """Earlier runs' deployments (or releases) with this run's, newest first; one read again keeps its new state."""
    seen = {tuple(d.get(k) for k in key): d for d in old if (d.get("at") or "") >= keep_since}
    seen.update({tuple(d.get(k) for k in key): d for d in new if (d.get("at") or "") >= keep_since})
    return sorted(seen.values(), key=lambda d: d.get("at") or "", reverse=True)


def _repo_fields(repo: dict) -> dict:
    codeowners = next((b["text"] for b in (repo.get("co1"), repo.get("co2"), repo.get("co3")) if b and b.get("text")), None)
    return {"default_branch": (repo.get("defaultBranchRef") or {}).get("name"), "codeowners": codeowners,
            "language": (repo.get("primaryLanguage") or {}).get("name"), "stars": repo.get("stargazerCount"),
            "private": bool(repo.get("isPrivate")),
            "releases": [{"tag": r["tagName"], "at": r.get("publishedAt") or r.get("createdAt"), "pre": bool(r.get("isPrerelease")),
                          "sha": (r.get("tagCommit") or {}).get("oid")}
                         for r in (repo.get("releases") or {}).get("nodes") or [] if r and not r.get("isDraft")],
            "deployments": [{"env": d.get("environment"), "at": d.get("createdAt"), "state": (d.get("latestStatus") or {}).get("state"),
                             "sha": d.get("commitOid"), "done": (d.get("latestStatus") or {}).get("createdAt")}
                            for d in (repo.get("deployments") or {}).get("nodes") or [] if d]}


# A cancelled run (often a duplicate replaced by a newer one) is not a failure.
FAILED_STATES = {"FAILURE", "ERROR", "TIMED_OUT", "STARTUP_FAILURE"}
PASSED_STATES = {"SUCCESS", "NEUTRAL", "SKIPPED"}


def _checks_query(numbers: list[int]) -> str:
    parts = "\n".join(
        f"  p{n}: pullRequest(number:{n}) {{ mergeable commits(last:1) {{ nodes {{ commit {{\n"
        "    checkSuites(first:15) { nodes { conclusion app { slug } } }\n"
        "    statusCheckRollup { contexts(first:60) { nodes { __typename\n"
        f"      ... on CheckRun {{ name conclusion isRequired(pullRequestNumber:{n}) }}\n"
        f"      ... on StatusContext {{ context state isRequired(pullRequestNumber:{n}) }} }} }} }} }} }} }} }}"
        for n in numbers)
    return (f"query($owner:String!,$name:String!) {{ rateLimit {{ cost remaining resetAt }} "
            f"repository(owner:$owner,name:$name) {{\n{parts}\n}} }}")


def collect_checks(gql, store: FlowStore, owner: str, name: str, batch: int = 20) -> int:
    """For open, ready PRs: which checks fail and whether each is required to merge, and whether CI waits for approval."""
    opened = store.open()
    todo = [n for n, p in opened.items() if not p.get("draft")]
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        try:
            repo = gql.query(_checks_query(chunk), {"owner": owner, "name": name}).data["repository"]
        except GraphQLError:
            # Keep the batches already read; the next run reads the rest.
            break
        for n in chunk:
            pull = repo.get(f"p{n}") or {}
            # A push to the base branch can create conflicts without touching the PR, so this is re-read every run.
            if pull.get("mergeable"):
                opened[n]["mgs"] = pull["mergeable"]
            commit = (((pull.get("commits") or {}).get("nodes") or [{}])[-1] or {}).get("commit") or {}
            contexts = ((commit.get("statusCheckRollup") or {}).get("contexts") or {}).get("nodes") or []
            passed = {c.get("name") or c.get("context") for c in contexts if c and (c.get("conclusion") or c.get("state")) in PASSED_STATES}
            # A check that also passed on the same commit (a re-run) is not failing.
            failing = [[c.get("name") or c.get("context"), bool(c.get("isRequired"))] for c in contexts
                       if c and (c.get("conclusion") or c.get("state")) in FAILED_STATES
                       and (c.get("name") or c.get("context")) not in passed]
            suites = (commit.get("checkSuites") or {}).get("nodes") or []
            opened[n]["chk"] = {"failing": failing, "ran": sorted({c.get("name") or c.get("context") for c in contexts if c} - {None}),
                                # Only GitHub Actions runs waiting for approval are the maintainers' move (not a CLA bot).
                                "awaiting": any(x and x.get("conclusion") == "ACTION_REQUIRED"
                                                and (x.get("app") or {}).get("slug") == "github-actions" for x in suites),
                                "required_any": any(c and c.get("isRequired") for c in contexts)}
    store.save_open(opened)
    return len(todo)
