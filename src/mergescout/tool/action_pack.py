import json
import statistics

from mergescout.labels import norm_label
from mergescout.tool.queries import rate_text, review_text
from mergescout.tool.refs import Ref

CHECKLIST = {
    "cla": "Sign the project's CLA before opening the PR",
    "dco": "Sign off every commit (git commit -s)",
    "issue_first": "Comment on the issue and wait for a maintainer's OK before coding",
    "ai_ban": "This project does not accept AI-written contributions; write it yourself",
    "ai_policy": "Follow the project's AI rules and say in the PR how you used AI",
    "no_outside_prs": "The project says it does not accept outside PRs right now",
    "issues_disabled": "Issues are turned off; ask in the project's discussion channel first",
}


def build_action_pack(snap, ref: Ref, status: dict | None = None) -> dict:
    issue, repo = snap.issue(ref.repo, ref.number), snap.repo(ref.repo)
    if issue is None or repo is None:
        raise ValueError(f"{ref.key} is not in today's snapshot; use check_issue for a live look.")
    walls = json.loads(repo["walls_json"])
    labels = {lb["label"]: lb for lb in json.loads(repo["labels_json"])}
    examples = snap.examples(repo["repo_id"])
    names = [norm_label(x) for x in json.loads(issue["labels"])]
    fix = next((labels[lb] for lb in names if lb in labels and labels[lb].get("enough")), None)
    if fix and fix.get("median_fix_lines") is not None:
        level = f"typical fix for this label here: {fix['median_fix_lines']:.0f} lines in {fix['median_fix_files']:.0f} files"
    elif examples:
        level = f"recent accepted outsider PRs: median {statistics.median(e['lines'] or 0 for e in examples):.0f} lines"
    else:
        level = "not enough evidence to size this yet"
    status = status or {"available": bool(issue["available"]),
                        "reasons": [b for b in (issue["blocked_by"] or "").split(", ") if b], "source": "snapshot",
                        "note": f"from the snapshot of {snap.built_at}; call check_issue for the live state"}
    steps = []
    if not status.get("available", True):
        steps.append(f"Stop: this issue is not free right now ({', '.join(status.get('reasons') or [])}). "
                     "Pick another one or ask the person working on it.")
    if any(w["wall"] == "issue_first" for w in walls):
        steps.append("Post the draft comment and wait for a maintainer's reply before writing code.")
    steps += ["Reproduce the problem locally and write down the exact steps.",
              "Plan a test that fails before your change and passes after it.",
              "Before opening the PR, explain the change in your own words in the description (no copy-paste).",
              "Keep the PR small and link the issue with 'Fixes #%d'." % ref.number]
    if any(w["wall"] in ("ai_policy", "ai_ban") for w in walls):
        steps.append("Check the project's AI rules (see the checklist) before using an AI assistant.")
    return {"issue": {"ref": ref.key, "url": f"https://github.com/{repo['name']}/issues/{ref.number}",
                      "title": issue["title"], "labels": json.loads(issue["labels"]), "asks": issue["body"]},
            "status": status,
            "repo": {"outsider_merge": rate_text(repo), "review": review_text(repo),
                     "how_prs_die": f"{repo['closed'] or 0} of {(repo['merged'] or 0) + (repo['closed'] or 0)} decided "
                                    f"outsider PRs were closed without merging (last {repo['window_days']} days)",
                     "contributing": bool(repo["contributing"]), "discussions": bool(repo["has_discussions"])},
            "accepted_examples": [{"url": f"https://github.com/{repo['name']}/pull/{e['number']}", "lines": e["lines"],
                                   "files": e["files"], "days_to_merge": e["days_to_merge"]} for e in examples],
            "policy_checklist": [f"{CHECKLIST[w['wall']]} (project text: \"{w['evidence']}\")" for w in walls
                                 if w["wall"] in CHECKLIST],
            "level": level, "next_steps": steps,
            "draft_comment": ("Hi! I'd like to work on this. My plan: <one or two lines on the approach>. "
                              "Does that sound right, and could it be assigned to me?")}
