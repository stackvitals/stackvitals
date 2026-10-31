import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from mergescout.labels import BEGINNER, norm_label
from mergescout.signals.rules import TRIAGE_LABEL_PATTERN

# Letters and digits only, like the index's tokenizer: "snake_case" quoted whole is a phrase, which detail=column rejects.
WORD = re.compile(r"[^\W_]+")
STOP = {"the", "and", "for", "with", "to", "of", "in", "on", "an", "is", "it", "be", "or", "not", "this", "that",
        "from", "by", "at", "as"}
NOTE = "Availability is from the snapshot; call check_issue before telling someone an issue is free."
PARTS = {"availability": "p_avail", "outsider_merge": "p_merge", "reply": "p_reply", "fixed_before": "p_fixed",
         "issue_quality": "p_quality", "multiplier": "mult"}
# Real queries (2026-10-16): "database" missed issues titled "SQLite lock" or "Postgres timeout".
_DB = ("db", "sql", "sqlite", "postgres", "postgresql", "mysql", "mongodb", "redis", "orm")
_DOCS = ("doc", "docs", "documentation", "readme", "typo", "tutorial", "guide")
SYNONYMS = {"database": _DB, "db": _DB, "sql": _DB, "doc": _DOCS, "docs": _DOCS, "documentation": _DOCS,
            "test": ("tests", "testing", "pytest", "unittest", "coverage"), "testing": ("test", "tests", "pytest"),
            "cli": ("command", "terminal", "flag", "subcommand"), "ui": ("frontend", "css", "component", "layout"),
            "frontend": ("ui", "css", "component"), "api": ("endpoint", "rest", "http"),
            "auth": ("login", "oauth", "authentication"), "login": ("auth", "oauth", "signin"),
            # Not "cache" or "memory": real titles use them for features ("X-Cache header", "load into memory").
            "performance": ("slow", "speed", "perf", "latency", "optimize", "benchmark"),
            "perf": ("performance", "slow")}


def fts_words(text: str | None) -> list[str]:
    return list(dict.fromkeys(w.lower() for w in WORD.findall(text or "") if len(w) >= 2 and w.lower() not in STOP))


def fts_query(text: str | None, synonyms: bool = False) -> str | None:
    # Every word becomes a quoted term, so search syntax in user text is never interpreted.
    words = fts_words(text)
    if synonyms:
        plural = lambda w: SYNONYMS.get(w[:-1], ()) if w.endswith("s") else ()
        words = list(dict.fromkeys(words + [s for w in words for s in SYNONYMS.get(w, plural(w))]))
    return " OR ".join(f'"{w}"' for w in words) or None


def parts(r: dict) -> dict:
    return {name: None if r[col] is None else round(r[col], 3) for name, col in PARTS.items()}


def _pct(x) -> int:
    return round((x or 0) * 100)


def _days(d) -> str:
    return "less than a day" if not d else "the last day" if d == 1 else f"the last {d} days"


def _rate(merged, decided, rate, low, high, enough, r: dict, who: str) -> str:
    if not enough:
        return f"not enough evidence yet ({decided} decided {who})"
    # Users read "last 4 days" as a slow repo; say plainly that a busy repo's newest PRs cover a short time.
    span = (f" over {_days(r['window_days'])}" if r["window_complete"]
            else f", from the newest 300 PRs, which cover only {_days(r['window_days'])}")
    return f"{_pct(rate)}% of {who} merged ({merged} of {decided}, likely {_pct(low)}-{_pct(high)}%){span}"


def rate_text(r: dict) -> str:
    merged = r["merged"] or 0
    return _rate(merged, merged + (r["closed"] or 0), r["merge_rate"], r["merge_low"], r["merge_high"],
                 r["merge_enough"], r, "outsider PRs")


def newcomer_text(r: dict) -> str:
    return _rate(r["newcomer_merged"] or 0, r["newcomer_decided"] or 0, r["newcomer_rate"], r["newcomer_low"],
                 r["newcomer_high"], r["newcomer_enough"], r, "first PRs by newcomers")


def review_text(r: dict) -> str:
    if not r["review_enough"]:
        return f"review time: not enough evidence yet ({r['reviewed'] or 0} maintainer reviews)"
    h = r["median_review_hours"]
    return f"maintainers usually first review outsider PRs within ~{h:.1f} h (median of {r['reviewed']})"


class Snapshot:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.meta = dict(self.db.execute("SELECT key, value FROM meta").fetchall())
        self.built_at = self.meta.get("built_at")
        # Files from schema 1.0 have no beginner column; "help wanted" then still counts as beginner.
        cols = {c[1] for c in self.db.execute("PRAGMA table_info(issues)")}
        self.beginner_col = "beginner" if "beginner" in cols else "opportunity"

    def _days_since(self, ts: str | None) -> int | None:
        if not ts or not self.built_at:
            return None
        return (datetime.fromisoformat(self.built_at.replace("Z", "+00:00"))
                - datetime.fromisoformat(ts.replace("Z", "+00:00"))).days

    def _rows(self, sql: str, params=()) -> list[dict]:
        return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def stats(self) -> dict:
        free = self.db.execute("SELECT count(*) FROM issues WHERE available = 1").fetchone()[0]
        langs = self._rows("SELECT language, count(*) AS issues FROM issues WHERE available = 1 AND language IS NOT NULL"
                           " GROUP BY language ORDER BY 2 DESC LIMIT 15")
        return {**{k: (int(v) if v.isdigit() else v) for k, v in self.meta.items()}, "free_issues": free,
                "top_languages": langs}

    def repo(self, name: str) -> dict | None:
        rows = self._rows("SELECT * FROM repos WHERE name = ? COLLATE NOCASE", (name,))
        return rows[0] if rows else None

    def _row(self, r: dict, detail: bool) -> dict:
        walls = [w["wall"] for w in json.loads(r["walls_json"]) if w.get("blocking")]
        labels = json.loads(r["labels"])
        names = {norm_label(x) for x in labels}
        # The shown score is the one the list is sorted by (base score with freshness), so lists read in order.
        out = {"issue": f"{r['repo']}#{r['number']}", "url": f"https://github.com/{r['repo']}/issues/{r['number']}",
               "title": r["title"], "labels": labels, "score": round(r["rank_score"], 2),
               "level": "beginner label" if names & BEGINNER else "help wanted" if "help wanted" in names
               else "no beginner label",
               "free": bool(r["available"]), "outsider_merge": rate_text(r), "review": review_text(r),
               "walls": walls, "updated": (r["updated_at"] or "")[:10]}
        if r.get("matched"):
            out["matched"] = r["matched"]
        untriaged = [x for x in labels if re.search(TRIAGE_LABEL_PATTERN, norm_label(x))]
        if untriaged and r["available"]:
            out["warning"] = (f"also labelled '{untriaged[0]}': a maintainer may not have confirmed it yet;"
                              " ask before starting")
        if r.get("kind") == "discussion":
            out["kind"] = "discussion or tracker, not a ready task"
        if not r["available"]:
            out["taken"] = r["blocked_by"]
        days = self._days_since(r["last_claim_at"])
        if r["claimers"] and days is not None:
            out["earlier_claims"] = (f"{r['claimers']} person(s) offered to work on it, the last {days} days ago;"
                                     " ask on the issue before starting")
        if detail:
            out.update({"base_score": round(r["score"], 2), "score_parts": parts(r), "notes": json.loads(r["repo_notes"]),
                        "stars": r["stars"], "dead_ends": r["dead_ends"], "interest_30d": r["interest_30d"],
                        "body": r["body"]})
        return out

    def _select(self, where: str, params: dict, order: str, limit: int, join_fts: bool = False) -> list[dict]:
        fts = "JOIN issues_fts f ON f.rowid = i.rowid" if join_fts else ""
        return self._rows(f"SELECT i.*, r.name AS repo, r.stars, r.merged, r.closed, r.merge_rate, r.merge_low,"
                          f" r.merge_high, r.merge_enough, r.window_days, r.window_complete, r.median_review_hours,"
                          f" r.review_enough, r.reviewed, r.walls_json, r.notes AS repo_notes FROM issues i {fts}"
                          f" JOIN repos r USING (repo_id)"
                          f" WHERE {where} ORDER BY {order}" + ("" if limit is None else " LIMIT :limit"),
                          params if limit is None else {**params, "limit": limit})

    def find_issues(self, language=None, topic=None, beginner_labels_only=False, min_score=0.0, allow_walls=True,
                    limit=10, detail=False) -> dict:
        # min_score applies to the score users see in the list (with freshness).
        where = ["i.available = 1", "i.rank_score >= :min_score"]
        params = {"min_score": min_score}
        if language:
            where.append("i.language = :language")
            params["language"] = language
        if beginner_labels_only:
            where.append(f"i.{self.beginner_col} = 1")
        if not allow_walls:
            where.append("r.blocking_walls = 0")
        q = fts_query(topic, synonyms=True)
        if topic and not q:
            return {"snapshot": self.built_at, "results": [],
                    "note": "The topic had no searchable words (very common words are ignored); try other words."}
        limit = max(1, min(limit, 50))
        state = {"seen": {}, "picked": [], "keys": set()}
        if q:
            # Real queries (2026-10-16): only 19 of 40 topic results had the topic in the title; those come first.
            for matched, match in (("title or label", f"{{title labels}} : ({q})"), ("text", q)):
                self._fill(" AND ".join(where + ["issues_fts MATCH :q"]), {**params, "q": match}, limit, state,
                           matched)
        else:
            self._fill(" AND ".join(where), params, limit, state, None)
        return {"snapshot": self.built_at, "note": NOTE, "results": [self._row(r, detail) for r in state["picked"]]}

    def _fill(self, where: str, params: dict, limit: int, state: dict, matched: str | None) -> None:
        # Real data (2026-10-15): one welcoming repo filled the whole top list; show at most 2 per repo.
        # Pages of the ranked index are read until the list is full, so a dominant repo cannot shorten it.
        seen, picked, page, offset = state["seen"], state["picked"], limit * 5, 0
        while len(picked) < limit and offset < 5000:
            rows = self._select(where, params, f"i.rank_score DESC LIMIT {page} OFFSET {offset}", None,
                                matched is not None)
            for r in rows:
                key = (r["repo_id"], r["number"])
                if key in state["keys"] or seen.get(r["repo_id"], 0) >= 2 or len(picked) >= limit:
                    continue
                seen[r["repo_id"]] = seen.get(r["repo_id"], 0) + 1
                state["keys"].add(key)
                picked.append({**r, "matched": matched} if matched else r)
            if len(rows) < page:
                break
            offset += page

    def issue(self, name: str, number: int) -> dict | None:
        rows = self._select("r.name = :name COLLATE NOCASE AND i.number = :number", {"name": name, "number": number},
                            "i.number", 1)
        return rows[0] if rows else None

    def examples(self, repo_id: int) -> list[dict]:
        return self._rows("SELECT number, merged_at, lines, files, days_to_merge FROM outsider_prs WHERE repo_id = ?"
                          " ORDER BY merged_at DESC", (repo_id,))

    def explain(self, name: str, number: int) -> dict | None:
        r = self.issue(name, number)
        repo = self.repo(name)
        if r is None or repo is None:
            return None
        labels = {lb["label"]: lb for lb in json.loads(repo["labels_json"])}
        return {"version": 1, "snapshot": self.built_at, "source": {"fetched_at": r["fetched_at"]},
                "issue": {"ref": f"{repo['name']}#{number}", "title": r["title"], "labels": json.loads(r["labels"]),
                          "assignees": r["assignees"], "linked_open_prs": r["linked_open_prs"],
                          "dead_ends": r["dead_ends"], "interest_30d": r["interest_30d"]},
                "availability": {"available": bool(r["available"]),
                                 "blocked_by": [b for b in (r["blocked_by"] or "").split(", ") if b],
                                 "last_claim_at": r["last_claim_at"], "claimers": r["claimers"]},
                "repo": {"outsider_merge": {"merged": repo["merged"], "decided": (repo["merged"] or 0) + (repo["closed"] or 0),
                                            "rate": repo["merge_rate"], "low": repo["merge_low"],
                                            "high": repo["merge_high"], "enough": bool(repo["merge_enough"]),
                                            "window_days": repo["window_days"],
                                            "window_complete": bool(repo["window_complete"])},
                         "newcomer_merge": {"merged": repo["newcomer_merged"], "decided": repo["newcomer_decided"],
                                            "rate": repo["newcomer_rate"], "low": repo["newcomer_low"],
                                            "high": repo["newcomer_high"], "enough": bool(repo["newcomer_enough"])},
                         "review_hours": {"median": repo["median_review_hours"], "n": repo["reviewed"],
                                          "enough": bool(repo["review_enough"])},
                         "excluded": {"bot_prs": repo["bot_prs"], "ai_prs": repo["ai_prs"],
                                      "insider_prs": repo["insider_prs"]}},
                "labels": [labels[lb] for lb in dict.fromkeys(norm_label(x) for x in json.loads(r["labels"]))
                           if lb in labels],
                "walls": json.loads(repo["walls_json"]),
                "score": {**parts(r), "total": round(r["score"], 3), "in_lists": round(r["rank_score"], 3)},
                "notes": json.loads(repo["notes"])}

    def repo_health(self, name: str, detail: bool = False) -> dict | None:
        r = self.repo(name)
        if r is None:
            return None
        counts = self.db.execute("SELECT count(*) FILTER (WHERE opportunity = 1),"
                                 " count(*) FILTER (WHERE opportunity = 1 AND available = 1) FROM issues WHERE repo_id = ?",
                                 (r["repo_id"],)).fetchone()
        out = {"repo": r["name"], "url": f"https://github.com/{r['name']}", "stars": r["stars"], "language": r["language"],
               "outsider_merge": rate_text(r), "newcomer_merge": newcomer_text(r),
               "review": review_text(r), "insiders": r["insiders"],
               "excluded_prs": {"bots": r["bot_prs"], "ai_agents": r["ai_prs"], "insiders": r["insider_prs"]},
               "walls": json.loads(r["walls_json"]), "beginner_issues": {"open": counts[0], "free": counts[1]},
               "how_to_reach": {"discussions": bool(r["has_discussions"]),
                                "contributing": f"https://github.com/{r['name']}/blob/HEAD/CONTRIBUTING.md"
                                if r["contributing"] else None,
                                "issues": f"https://github.com/{r['name']}/issues"},
               "snapshot": self.built_at}
        if detail:
            out["labels"] = json.loads(r["labels_json"])
            out["accepted_outsider_prs"] = self.examples(r["repo_id"])
        return out

    def repos_needing_help(self, language=None, limit=10) -> dict:
        # Welcoming to outsiders (enough evidence, merge rate at least 50% even at the low end) but few maintainers.
        built = datetime.fromisoformat(self.built_at.replace("Z", "+00:00")) if self.built_at else datetime.now(timezone.utc)
        recent = (built - timedelta(days=90)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = self._rows("SELECT * FROM repos WHERE merge_enough = 1 AND merge_low >= 0.5 AND insiders <= 3"
                          " AND coalesce(archived, 0) = 0 AND pushed_at >= :recent"
                          " AND (:language IS NULL OR language = :language) ORDER BY outsider_prs DESC LIMIT :limit",
                          {"recent": recent, "language": language, "limit": max(1, min(limit, 50))})
        return {"snapshot": self.built_at, "results": [
            {"repo": r["name"], "url": f"https://github.com/{r['name']}", "language": r["language"],
             "why": f"{r['insiders']} active maintainers handle {r['outsider_prs']} outsider PRs; {rate_text(r)};"
                    f" {review_text(r)}"} for r in rows]}

    def similar_issues(self, name: str, number: int, limit: int = 5) -> dict:
        base = self.issue(name, number)
        if base is None:
            return {"snapshot": self.built_at, "results": []}
        # The rarest title words that other issues share: common words ("add", "error") match thousands and are slow.
        counts = {w: self.db.execute("SELECT count(*) FROM issues_fts WHERE issues_fts MATCH ?", (f'"{w}"',)).fetchone()[0]
                  for w in fts_words(base["title"])}
        rare = [w for w, n in sorted(counts.items(), key=lambda kv: kv[1]) if n >= 2][:3]
        q = " OR ".join(f'"{w}"' for w in rare) or None
        rows = self._select("issues_fts MATCH :q AND i.available = 1 AND NOT (i.repo_id = :rid AND i.number = :n)",
                            {"q": q, "rid": base["repo_id"], "n": number}, "bm25(issues_fts), i.rank_score DESC",
                            max(1, min(limit, 20)), True) if q else []
        return {"snapshot": self.built_at, "results": [self._row(r, False) for r in rows]}

    def with_repo_stats(self, items: list[dict]) -> list[dict]:
        out = []
        for it in items:
            r = self.repo(it["repo"])
            if r is not None:
                out.append({**it, "outsider_merge": rate_text(r), "review": review_text(r),
                            "walls": [w["wall"] for w in json.loads(r["walls_json"]) if w.get("blocking")]})
        return out
