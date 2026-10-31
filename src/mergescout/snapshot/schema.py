# The file every user downloads; bump the major version only for changes old tools cannot read.
SCHEMA_VERSION = "1.1"
SCHEMA_MAJOR = 1

DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE repos (
  repo_id INTEGER PRIMARY KEY, name TEXT NOT NULL, stars INTEGER, language TEXT COLLATE NOCASE, pushed_at TEXT,
  archived INTEGER, license TEXT, has_discussions INTEGER, open_issues INTEGER, open_prs INTEGER, insiders INTEGER,
  outsider_prs INTEGER, merged INTEGER, closed INTEGER, merge_rate REAL, merge_low REAL, merge_high REAL,
  merge_enough INTEGER, newcomer_merged INTEGER, newcomer_decided INTEGER, newcomer_rate REAL, newcomer_low REAL,
  newcomer_high REAL, newcomer_enough INTEGER, reviewed INTEGER, median_review_hours REAL, review_enough INTEGER,
  window_days INTEGER, window_complete INTEGER, ai_prs INTEGER, bot_prs INTEGER, insider_prs INTEGER,
  blocking_walls INTEGER NOT NULL, walls_json TEXT NOT NULL, labels_json TEXT NOT NULL, notes TEXT NOT NULL,
  contributing INTEGER,
  fetched_at TEXT);
CREATE UNIQUE INDEX repos_name ON repos (name COLLATE NOCASE);
CREATE TABLE issues (
  repo_id INTEGER NOT NULL, number INTEGER NOT NULL, title TEXT, body TEXT, labels TEXT NOT NULL,
  language TEXT COLLATE NOCASE, created_at TEXT, updated_at TEXT, available INTEGER NOT NULL,
  opportunity INTEGER NOT NULL, blocked_by TEXT, assignees INTEGER, linked_open_prs INTEGER, dead_ends INTEGER,
  claimers INTEGER, last_claim_at TEXT, interest_30d INTEGER, score REAL NOT NULL, rank_score REAL NOT NULL,
  p_avail REAL, p_merge REAL, p_reply REAL, p_fixed REAL, p_quality REAL, mult REAL, fetched_at TEXT,
  beginner INTEGER NOT NULL DEFAULT 0, kind TEXT,
  UNIQUE (repo_id, number));
CREATE INDEX issues_rank ON issues (available, language, rank_score DESC);
CREATE INDEX issues_rank_all ON issues (available, rank_score DESC);
CREATE TABLE outsider_prs (repo_id INTEGER NOT NULL, number INTEGER NOT NULL, merged_at TEXT, lines INTEGER,
  files INTEGER, days_to_merge REAL);
CREATE INDEX outsider_prs_repo ON outsider_prs (repo_id);
-- detail=column: single-word search only, about half the index size.
CREATE VIRTUAL TABLE issues_fts USING fts5(title, labels, body, content='issues', content_rowid='rowid',
  tokenize='porter unicode61', detail=column);
"""
