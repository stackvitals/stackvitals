import csv
import random
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import duckdb
import httpx

from mergescout.crawl.queries import RL
from mergescout.owners import owner_logins

OWNER_FILES = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS", "MAINTAINERS", "MAINTAINERS.md", "OWNERS")


def sample_repos(repo_stats: list[dict], n: int = 30, seed: int = 7) -> list[int]:
    tiers = [(100, 999), (1000, 9999), (10000, None)]
    rng = random.Random(seed)
    picked = []
    for lo, hi in tiers:
        pool = sorted(r["repo_id"] for r in repo_stats if r["outsider_prs"] >= 20 and r["stars"] >= lo
                      and (hi is None or r["stars"] <= hi))
        picked += rng.sample(pool, min(n // len(tiers), len(pool)))
    return picked


def score_identity(predicted: dict[str, str], confirmed_insiders: set[str], pr_counts: dict[str, int]) -> dict:
    insiders = [u for u, k in predicted.items() if k == "insider"]
    missed = sorted(u for u, k in predicted.items() if k == "outsider" and u in confirmed_insiders)
    outsider_prs = sum(pr_counts.get(u, 0) for u, k in predicted.items() if k == "outsider")
    confirmed = [u for u in insiders if u in confirmed_insiders]
    # Unconfirmed insiders are not errors: most employees keep their org membership private.
    return {"insider_confirmed": len(confirmed), "insider_checkable": len(confirmed),
            "insider_unconfirmed": len(insiders) - len(confirmed), "missed_insiders": missed,
            "missed_pr_share": (sum(pr_counts.get(u, 0) for u in missed) / outsider_prs) if outsider_prs else 0.0}


def spearman(a: list[float], b: list[float]) -> float:
    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        r = [0.0] * len(xs)
        for rank, i in enumerate(order):
            r[i] = float(rank)
        return r
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    d2 = sum((x - y) ** 2 for x, y in zip(ra, rb))
    return 1 - 6 * d2 / (n * (n * n - 1))


OWNER_QUERY = "query($owner: String!, $name: String!) { " + RL + " repository(owner: $owner, name: $name) { " + " ".join(
    f'f{i}: object(expression: "HEAD:{f}") {{ ... on Blob {{ text }} }}' for i, f in enumerate(OWNER_FILES)) + " } }"


def _rows(con: duckdb.DuckDBPyConnection, sql: str) -> list[dict]:
    cur = con.execute(sql)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def _parquet(signals: Path, table: str) -> str:
    quoted = (signals / f"{table}.parquet").as_posix().replace("'", "''")
    return f"read_parquet('{quoted}')"


def run_check(signals: Path, out: Path, gql, http: httpx.Client, log=print) -> dict:
    con = duckdb.connect()
    stats = _rows(con, f"SELECT repo_id, name, stars, outsider_prs FROM {_parquet(signals, 'repo_stats')} "
                       "WHERE name IS NOT NULL AND stars IS NOT NULL AND outsider_prs IS NOT NULL")
    people = _rows(con, f"SELECT repo_id, lower(login) AS login, kind, prs, activity FROM {_parquet(signals, 'people')} "
                        "WHERE kind IN ('insider', 'outsider')")
    by_repo = {}
    for p in people:
        by_repo.setdefault(p["repo_id"], []).append(p)
    names = {s["repo_id"]: s for s in stats}
    rows, missed_prs, outsider_prs = [], 0, 0
    for repo_id in sample_repos(stats):
        repo = names[repo_id]
        owner, name = repo["name"].split("/", 1)
        data = gql.query(OWNER_QUERY, {"owner": owner, "name": name}).data["repository"] or {}
        texts = [(data.get(f"f{i}") or {}).get("text") or "" for i in range(len(OWNER_FILES))]
        confirmed = owner_logins("\n".join(texts)) | {owner.lower()}
        ppl = by_repo.get(repo_id, [])
        top = [p["login"] for kind in ("insider", "outsider")
               for p in sorted((p for p in ppl if p["kind"] == kind), key=lambda p: -p["activity"])[:20]]

        def member(login, owner=owner):
            # 204 means a public member of the owning org (users and private members answer 404).
            return login, http.get(f"https://api.github.com/orgs/{owner}/public_members/{login}").status_code == 204
        with ThreadPoolExecutor(8) as pool:
            confirmed |= {login for login, yes in pool.map(member, [u for u in top if u not in confirmed]) if yes}
        s = score_identity({p["login"]: p["kind"] for p in ppl}, confirmed, {p["login"]: p["prs"] for p in ppl})
        repo_outsider_prs = sum(p["prs"] for p in ppl if p["kind"] == "outsider")
        missed_prs += sum(p["prs"] for p in ppl if p["login"] in s["missed_insiders"])
        outsider_prs += repo_outsider_prs
        rows.append({"repo": repo["name"], "stars": repo["stars"],
                     "insiders": sum(p["kind"] == "insider" for p in ppl),
                     "outsiders": sum(p["kind"] == "outsider" for p in ppl),
                     "owner_files": sum(bool(x) for x in texts),
                     "insider_confirmed": s["insider_confirmed"], "insider_unconfirmed": s["insider_unconfirmed"],
                     "missed_insiders": " ".join(s["missed_insiders"]), "missed_pr_share": round(s["missed_pr_share"], 4)})
        log(f"{repo['name']}: {s['insider_confirmed']} insiders confirmed, missed {s['missed_insiders']} "
            f"({s['missed_pr_share']:.1%} of outsider PRs)")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["repo"])
        writer.writeheader()
        writer.writerows(rows)
    total = {"repos": len(rows), "missed_pr_share": missed_prs / outsider_prs if outsider_prs else 0.0}
    log(f"total: {total['repos']} repos, missed insiders wrote {total['missed_pr_share']:.2%} of outsider PRs")
    return total


def _last_month_median(doc: dict, now: datetime) -> float | None:
    # OpenDigger keys months as "YYYY-MM"; the current month is still incomplete.
    q = doc.get("quantile_2") or {}
    months = sorted(k for k in q if re.fullmatch(r"\d{4}-\d{2}", k) and k < now.strftime("%Y-%m"))
    return q[months[-1]] if months else None


def run_opendigger(signals: Path, repos: int, http: httpx.Client, log=print, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    con = duckdb.connect()
    ours = _rows(con, f"SELECT name, median_review_hours FROM {_parquet(signals, 'repo_stats')} "
                      f"WHERE review_enough AND name IS NOT NULL ORDER BY reviewed DESC LIMIT {int(repos)}")

    def fetch(row):
        resp = http.get(f"https://oss.open-digger.cn/github/{row['name']}/change_request_response_time.json")
        return row, (resp.json() if resp.status_code == 200 else None)
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(fetch, ours))
    sample = next((doc for _, doc in results if doc), None)
    if sample is None or "quantile_2" not in sample:
        log(f"OpenDigger has no usable data (keys: {sorted(sample or {})[:12]})")
        return {"n": 0, "spearman": None}
    pairs = [(row["median_review_hours"], _last_month_median(doc, now) * 24) for row, doc in results
             if doc and _last_month_median(doc, now) is not None]
    rho = spearman([a for a, _ in pairs], [b for _, b in pairs]) if len(pairs) > 2 else None
    log(f"OpenDigger: {len(pairs)} of {len(ours)} repos matched, Spearman {None if rho is None else round(rho, 3)}")
    return {"n": len(pairs), "spearman": rho}
