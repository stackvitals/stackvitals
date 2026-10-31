"""Which jobs can pass and fail on the same code because they read the PR itself: workflows that also run when a PR's
description, labels or reviewers change, and jobs in them that read the PR's title, description or labels (a PR
template check). A different result on the same code is not a flake there; re-runs that pass still are."""
import re
from datetime import date, timedelta

from stackvitals.ci.api import APIError, OutOfBudget

PR_EVENTS = ("pull_request", "pull_request_target")
# Activity types that change the PR but not its code.
METADATA_TYPES = {"edited", "labeled", "unlabeled", "assigned", "unassigned", "review_requested", "review_request_removed",
                  "milestoned", "demilestoned", "locked", "unlocked", "auto_merge_enabled", "auto_merge_disabled",
                  "enqueued", "dequeued"}
ON_KEY = re.compile(r"""^(?:on|"on"|'on'|true)\s*:(.*)$""")
# What a job reads that changes without a code change; `if:` lines only gate the job, so they don't count.
READS_PR = re.compile(r"(?:github\.event|context\.payload)\.(?:pull_request\.(?:title|body|labels|assignees|requested_reviewers"
                      r"|requested_teams|milestone)|label\b|changes\b)|semantic-pull-request|pr-title|required-labels|pr-lint"
                      r"|conventional-pr"
                      # A script that fetches the PR and reads its labels (real data: aiohttp's "Backport label added").
                      r"|\.labels\.(?:find|some|filter|map|includes|length)\b",
                      re.IGNORECASE)


def _words(text: str) -> set[str]:
    return {w.strip().strip("'\"") for w in text.split(",")}


def _lines(text: str):
    # (indent, stripped) for lines with content, comments and the byte-order mark removed.
    for raw in text.lstrip("﻿").splitlines():
        line = re.sub(r"\s+#.*$", "", raw).rstrip()
        if line.strip() and not line.lstrip().startswith("#"):
            yield len(line) - len(line.lstrip()), line.strip()


def pr_metadata_triggered(text: str) -> bool:
    """True when the workflow's `on:` lists pull_request or pull_request_target with a metadata activity type.
    A small line reader for this one question (no YAML library needed); unusual layouts read as False."""
    in_on, event_indent, in_pr, types_indent = False, None, False, None
    for indent, stripped in _lines(text):
        if indent == 0:
            in_on, event_indent, in_pr, types_indent = bool(ON_KEY.match(stripped)), None, False, None
            continue
        if not in_on:
            continue
        if event_indent is None or indent <= event_indent:
            event_indent, types_indent = indent, None
            key, _, rest = stripped.partition(":")
            in_pr = key.strip().strip("'\"") in PR_EVENTS
            # Inline form: pull_request: {types: [edited]}
            found = re.search(r"types\s*:\s*\[([^\]]*)\]", rest)
            if in_pr and found and _words(found.group(1)) & METADATA_TYPES:
                return True
            continue
        if not in_pr:
            continue
        # List items may sit at the same indent as `types:` in YAML.
        if types_indent is not None and indent >= types_indent and stripped.startswith("-"):
            if stripped[1:].strip().strip("'\"") in METADATA_TYPES:
                return True
            continue
        types_indent = None
        if stripped.startswith("types:"):
            value = stripped[len("types:"):].strip()
            if value.startswith("["):
                if _words(value.strip("[]")) & METADATA_TYPES:
                    return True
            elif value:
                if value.strip("'\"") in METADATA_TYPES:
                    return True
            else:
                types_indent = indent
    return False


def metadata_jobs(text: str) -> set[str]:
    """Ids and names of the jobs that read the PR's title, description or labels, in a workflow that also runs on PR
    metadata changes; empty otherwise."""
    if not pr_metadata_triggered(text):
        return set()
    out, in_jobs, job_indent, job, name, reads, child_indent, gate_indent = set(), False, None, None, None, False, None, None

    def close():
        if job and reads:
            out.update(n for n in (job, name) if n)
    for indent, stripped in _lines(text):
        if indent == 0:
            close()
            in_jobs, job_indent, job, name, reads = stripped.startswith("jobs:"), None, None, None, False
            continue
        if not in_jobs:
            continue
        if job_indent is None or indent <= job_indent:
            close()
            job_indent, job, name, reads = indent, stripped.split(":")[0].strip().strip("'\""), None, False
            child_indent = gate_indent = None
            continue
        if gate_indent is not None and indent > gate_indent:
            continue  # the rest of a multi-line `if:`
        gate_indent = None
        child_indent = child_indent or indent
        if stripped.removeprefix("- ").startswith("if:"):
            # In "- if:" the step's other keys sit two columns in; only deeper lines continue the condition.
            gate_indent = indent + 2 if stripped.startswith("- ") else indent
            continue
        if indent == child_indent and stripped.startswith("name:"):
            name = stripped[len("name:"):].strip().strip("'\"")
        if READS_PR.search(stripped):
            reads = True
    close()
    return out


CHECK_DAYS = 7
MAX_READS = 5


def pr_metadata_workflows(api, store, data: dict, ref: str | None, today: str) -> dict[str, set[str]]:
    """{workflow path: jobs that read the PR} for workflows run by PR events. Each file is read at most once a week
    (a few per run) and the answer is kept in the data branch; a file that can't be read keeps what was known."""
    state = store.state()
    seen = dict(state.get("triggers") or {})
    paths = sorted({r["path"] for r in data.get("runs") or []
                    if r.get("ev") in PR_EVENTS and (r.get("path") or "").startswith(".github/workflows/")})
    fresh = (date.fromisoformat(today) - timedelta(days=CHECK_DAYS)).isoformat()
    reads = 0
    for path in paths:
        old = seen.get(path) or {}
        if ("edits" in old and old.get("checked", "") > fresh) or reads >= MAX_READS:
            continue
        reads += 1
        try:
            text = api.file(path, ref).decode("utf-8", "replace")
            jobs, edits = sorted(metadata_jobs(text)), pr_metadata_triggered(text)
        except APIError:
            jobs, edits = old.get("jobs") or [], bool(old.get("edits"))
        except OutOfBudget:
            break
        seen[path] = {"jobs": jobs, "edits": edits, "checked": today}
    if seen != state.get("triggers"):
        store.save_state({**state, "triggers": seen})
    return {p: set(v["jobs"]) for p, v in seen.items() if v.get("jobs")}


def pr_edit_workflows(store) -> set[str]:
    """Workflows that also run when a PR's title, description or labels change (read by pr_metadata_workflows)."""
    return {p for p, v in (store.state().get("triggers") or {}).items() if v.get("edits") or v.get("jobs")}
