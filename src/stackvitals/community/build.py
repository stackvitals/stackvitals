from datetime import datetime

from stackvitals.community.analyze import (answers_by_tenure, bench_facts, cohorts, dependency, elephant, first_answer,
                                           funnel, insiders,
                                           newcomers_waiting, peer_range, quarterly, regular_responders, score, star_trend,
                                           traffic_summary, weekly_changes)
from stackvitals.connectors.discourse import answers as forum_answers
from stackvitals.core.time import iso

WAITING_ROWS = 50


def _lever(bench: dict | None) -> dict | None:
    # The crawl's newcomer table: what happened to first-timers across public repos, by how long they waited.
    table = (bench or {}).get("newcomers") if isinstance(bench, dict) else None
    if not isinstance(table, dict) or not isinstance(table.get("by_answer"), list) or not table.get("newcomers"):
        return None
    rows = [b for b in table["by_answer"] if isinstance(b, dict) and isinstance(b.get("returned"), (int, float))
            and isinstance(b.get("newcomers"), int) and isinstance(b.get("bucket"), str)]
    outcome = [b for b in table.get("by_outcome") or [] if isinstance(b, dict) and isinstance(b.get("returned"), (int, float))]
    return {"newcomers": table["newcomers"], "repos": table.get("repos"), "by_answer": rows, "by_outcome": outcome} if rows else None


def build(prs: dict, issues: dict, stars: dict, traffic: dict, repo: dict, now: datetime, bench: dict | None = None,
          star_bench: dict | None = None, context: dict | None = None, affiliation: dict | None = None,
          discussions: dict | None = None, forum: list[dict] | None = None, chat: list[dict] | None = None) -> dict:
    """Everything Community shows, from Team Flow's PR history, the issues, the star history and (if kept) traffic."""
    all_prs = (prs.get("open") or []) + (prs.get("closed") or [])
    all_issues = (issues.get("open") or []) + (issues.get("closed") or [])
    language, star_count = repo.get("language"), repo.get("stars")
    # Who the maintainers are is decided once for the whole page.
    ins = insiders(all_prs, all_issues)
    # Issues count an answer from a maintainer or a regular responder; PRs from a maintainer.
    resp = set(ins) | regular_responders(all_prs, all_issues, ins, now)
    facts = bench_facts(all_prs, now)
    waiting = newcomers_waiting(all_prs, all_issues, now, ins, resp)
    carried = dependency(all_prs, now)
    if carried:
        # Similar public repos' typical values beside this repo's, not folded into the score (it keeps one meaning).
        carried["peers"] = {m: peer_range(bench, language, star_count, m) for m in ("bus_factor", "top_share")}
    return {"generated": iso(now), "facts": facts, "score": score(facts, bench, language, star_count),
            "has_bench": bool(bench),
            "funnel": funnel(all_prs, all_issues, now, ins),
            "answers": first_answer(all_prs, all_issues, now, ins=ins, resp=resp,
                                    discussions=(discussions or {}).get("open", []) + (discussions or {}).get("closed", [])),
            "waiting": waiting[:WAITING_ROWS], "waiting_total": len(waiting), "lever": _lever(bench),
            "stars": star_trend((stars or {}).get("weeks") or {}, star_count, now, star_bench, language),
            "traffic": traffic_summary(traffic or {}, now),
            "quarters": quarterly(all_prs, all_issues, now, ins=ins, resp=resp),
            "dependency": carried, "tenure": answers_by_tenure(all_prs, all_issues, now, ins=ins, resp=resp),
            "changes": weekly_changes(all_prs, all_issues, now, ins, resp),
            # What the repo states about itself (read weekly), the organisations behind the work, and newcomer cohorts.
            "context": context, "orgs": elephant(all_prs, affiliation, now) if affiliation is not None else None,
            "cohorts": cohorts(all_prs, all_issues, now, ins),
            # A Discourse forum, when connected: questions answered there instead of in issues.
            "forum": forum_answers(forum, now) if forum else None, "chat": forum_answers(chat, now) if chat else None}
