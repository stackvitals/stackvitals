import duckdb

from mergescout.signals.rules import (AI_AGENT_BOT_NAMES, AI_AGENT_LOGINS, BOT_NAME_PATTERN, HUMAN_BOT_NAMES,
                                      KNOWN_BOTS, UNKNOWN_LOGINS)


def _quoted(names) -> str:
    return ", ".join("'" + n.replace("'", "''") + "'" for n in sorted(names))


def build_people(con: duckdb.DuckDBPyConnection) -> None:
    # Insiders are found by what they do (merging, listed roles), not only by GitHub's association label.
    con.execute(f"""
        CREATE OR REPLACE TABLE people AS
        WITH acts AS (
            SELECT repo_id, author_login AS login, author_association AS assoc, author_type AS typ, 'pr' AS act FROM prs
            UNION ALL SELECT repo_id, merged_by, NULL, NULL, 'merged_other' FROM prs
                WHERE state = 'MERGED' AND merged_by IS NOT NULL AND merged_by IS DISTINCT FROM author_login
            UNION ALL SELECT repo_id, merged_by, NULL, NULL, 'self_merge' FROM prs
                WHERE state = 'MERGED' AND merged_by = author_login
            UNION ALL SELECT repo_id, first_review_by, first_review_association, NULL, 'review' FROM prs
            UNION ALL SELECT repo_id, first_human_review_by, first_human_review_association, NULL, 'review' FROM prs
            UNION ALL SELECT repo_id, author_login, author_association, NULL, 'issue' FROM issues
            UNION ALL SELECT repo_id, author_login, author_association, author_type, 'comment' FROM comments
            UNION ALL SELECT repo_id, author_login, author_association, NULL, 'issue' FROM closed_issues),
        agg AS (
            SELECT repo_id, login,
                bool_or(typ = 'Bot' OR lower(login) LIKE '%[bot]' OR lower(login) IN ({_quoted(KNOWN_BOTS)})
                        OR (regexp_matches(lower(login), '{BOT_NAME_PATTERN}')
                            AND NOT regexp_matches(lower(login), '{HUMAN_BOT_NAMES}'))) AS bot,
                bool_or(assoc IN ('OWNER', 'MEMBER', 'COLLABORATOR')) AS listed,
                bool_or(act = 'merged_other') AS merges_others,
                bool_or(act = 'self_merge') AS self_merges,
                count(*) AS activity,
                count(*) FILTER (WHERE act = 'pr') AS prs
            FROM acts
            WHERE login IS NOT NULL AND lower(login) NOT IN ({_quoted(UNKNOWN_LOGINS)})
            GROUP BY repo_id, login),
        -- People named in CODEOWNERS / MAINTAINERS / OWNERS are maintainers even when they rarely merge.
        owners AS (
            SELECT DISTINCT repo_id, lower(o) AS l FROM (SELECT repo_id, unnest(owner_logins) AS o FROM repo_meta))
        SELECT a.repo_id, a.login,
            CASE WHEN bot THEN 'bot' WHEN listed OR merges_others OR self_merges OR ow.l IS NOT NULL THEN 'insider'
                 ELSE 'outsider' END AS kind,
            concat_ws(', ', CASE WHEN bot THEN 'bot account' END, CASE WHEN listed THEN 'listed role' END,
                      CASE WHEN merges_others THEN 'merges others' END, CASE WHEN self_merges THEN 'merges own' END,
                      CASE WHEN ow.l IS NOT NULL THEN 'in owner files' END) AS reasons,
            activity, prs
        FROM agg a LEFT JOIN owners ow ON ow.repo_id = a.repo_id AND ow.l = lower(a.login)""")


def build_pr_class(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(f"""
        CREATE OR REPLACE VIEW pr_class AS
        SELECT p.*, CASE
            WHEN p.author_login IS NULL OR lower(p.author_login) IN ({_quoted(UNKNOWN_LOGINS)}) THEN 'unknown'
            WHEN replace(lower(p.author_login), '[bot]', '') IN ({_quoted(AI_AGENT_LOGINS)}) THEN 'ai'
            WHEN replace(lower(p.author_login), '[bot]', '') IN ({_quoted(AI_AGENT_BOT_NAMES)})
                 AND (p.author_type = 'Bot' OR lower(p.author_login) LIKE '%[bot]') THEN 'ai'
            WHEN pe.kind = 'bot' OR p.ai_tag = 'bot' THEN 'bot'
            WHEN p.ai_tag IS NOT NULL THEN 'ai'
            WHEN pe.kind = 'insider' THEN 'insider'
            ELSE 'outsider' END AS author_class,
            -- The author alone, as the suite's app decides it: a person's AI-assisted PR is still that person's.
            CASE
            WHEN p.author_login IS NULL OR lower(p.author_login) IN ({_quoted(UNKNOWN_LOGINS)}) THEN 'unknown'
            WHEN replace(lower(p.author_login), '[bot]', '') IN ({_quoted(AI_AGENT_LOGINS)}) THEN 'agent'
            WHEN replace(lower(p.author_login), '[bot]', '') IN ({_quoted(AI_AGENT_BOT_NAMES)})
                 AND (p.author_type = 'Bot' OR lower(p.author_login) LIKE '%[bot]') THEN 'agent'
            WHEN pe.kind = 'bot' OR p.ai_tag = 'bot' THEN 'bot'
            WHEN pe.kind = 'insider' THEN 'insider'
            ELSE 'outsider' END AS author_role
        FROM prs p LEFT JOIN people pe ON pe.repo_id = p.repo_id AND pe.login = p.author_login""")
