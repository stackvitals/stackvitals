import json
import random
import sqlite3
import time

from mergescout.snapshot.schema import DDL, SCHEMA_VERSION
from mergescout.tool.queries import Snapshot

WORDS = "database etl cache parser cli docs test api auth logging retry config plugin ui build".split()


def test_find_issues_p95_under_100_ms_on_300k_issues(tmp_path):
    rng = random.Random(1)
    path = tmp_path / "big.sqlite"
    db = sqlite3.connect(path)
    db.executescript(DDL)
    langs = ["Python", "Go", "Rust", "TypeScript", "Java"]
    db.executemany("INSERT INTO repos (repo_id, name, language, blocking_walls, walls_json, labels_json, notes,"
                   " merge_enough, merged, closed, merge_rate, merge_low, merge_high) VALUES (?, ?, ?, 0, '[]', '[]',"
                   " '[]', 1, 9, 1, 0.9, 0.6, 0.98)", [(i, f"o{i}/r{i}", langs[i % 5]) for i in range(5000)])
    rows = []
    for n in range(300_000):
        title = " ".join(rng.sample(WORDS, 4))
        rows.append((n % 5000, n, title, title, json.dumps(["good first issue"]), langs[n % 5000 % 5],
                     rng.random() > 0.3, rng.random() > 0.8, rng.random(), rng.random()))
    db.executemany("INSERT INTO issues (repo_id, number, title, body, labels, language, available, opportunity, score,"
                   " rank_score) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    db.execute("INSERT INTO issues_fts (rowid, title, labels, body) SELECT rowid, title, labels, body FROM issues")
    db.executemany("INSERT INTO meta VALUES (?, ?)", [("schema_version", SCHEMA_VERSION), ("built_at", "x"),
                                                    ("issues", "300000"), ("repos", "5000")])
    db.commit()
    db.execute("ANALYZE")
    db.close()
    snap = Snapshot(path)
    times = []
    for i in range(200):
        start = time.perf_counter()
        snap.find_issues(language=langs[i % 5], topic=WORDS[i % len(WORDS)] if i % 2 else None, limit=10)
        times.append(time.perf_counter() - start)
    times.sort()
    assert times[int(len(times) * 0.95)] < 0.1
