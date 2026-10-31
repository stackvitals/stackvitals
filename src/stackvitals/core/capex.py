"""Effort and capitalisation for finance: one row per merged pull request into the default branch (month, link, kind of
work and how it was decided, its epic or project when Jira or Linear is connected, written by a coding agent or a person)
as a CSV an auditor can follow back to GitHub, and a monthly summary of author-weeks by kind of work with the agent share.
Feature work is what teams usually capitalise; the rule stays the team's and its auditor's, these are the facts behind it."""
import csv
import io
from collections import defaultdict
from datetime import datetime, timedelta

from stackvitals.core.ai_outcomes import mode
from stackvitals.core.investment import classify

COLUMNS = ("month", "merged_at", "pr", "url", "title", "kind", "decided_by", "epic", "author", "author_kind")


def rows(prs: list[dict], repo: str, now: datetime, private: bool, base: str | None = None, months: int = 12,
         rules: dict | None = None, tracker_types: dict | None = None, epics: dict | None = None) -> list[dict]:
    """Merged PRs of the last `months` months, oldest first; a public repo's rows carry no titles."""
    since = (now - timedelta(days=31 * months)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for p in sorted((p for p in prs if p.get("mg") and p["mg"] >= since and (not base or not p.get("base") or p["base"] == base)),
                    key=lambda p: p["mg"]):
        kind, how = classify(p, rules, (tracker_types or {}).get(p["n"]))
        row = {"month": p["mg"][:7], "merged_at": p["mg"], "pr": p["n"], "url": f"https://github.com/{repo}/pull/{p['n']}",
               "kind": kind, "decided_by": how, "epic": (epics or {}).get(p["n"]) or "",
               "author": "agent" if mode(p) == "agent" else "person", "author_kind": mode(p),
               "_login": (p.get("au") or "").lower()}  # for author-weeks only; never written to the file
        if private:
            row["title"] = (p.get("ti") or "")[:200]
        out.append(row)
    return out


def to_csv(rows: list[dict]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=[c for c in COLUMNS if not rows or c in rows[0]], extrasaction="ignore",
                       lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue()


def summary(rows: list[dict]) -> list[dict]:
    """Per month: merged PRs, author-weeks by kind of work (one author's PRs of one kind in one ISO week count once),
    the feature share and how many PRs coding agents wrote."""
    months = defaultdict(lambda: {"prs": 0, "agent_prs": 0, "weeks": defaultdict(set), "kinds": defaultdict(int)})
    for r in rows:
        m = months[r["month"]]
        m["prs"] += 1
        m["agent_prs"] += r["author"] == "agent"
        m["kinds"][r["kind"]] += 1
        week = datetime.fromisoformat(r["merged_at"].replace("Z", "+00:00")).isocalendar()[:2]
        m["weeks"][r["kind"]].add((r.get("_login"), week))
    return [{"month": month, "prs": m["prs"], "agent_prs": m["agent_prs"], "kinds": dict(m["kinds"]),
             "author_weeks": {k: len(v) for k, v in m["weeks"].items()},
             "feature_share": round(m["kinds"].get("feature", 0) / m["prs"], 4) if m["prs"] else None}
            for month, m in sorted(months.items())]
