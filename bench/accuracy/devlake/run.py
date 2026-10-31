"""The head-to-head run (preregistration.md), on a GitHub Actions runner with Docker: start Apache DevLake from its
release's docker-compose, configure it only through its REST API, collect the repos, read DORA from its own domain tables
with its dashboard SQL; then run StackVitals on the same repos; time every stage and record the footprint.

    GH_TOKEN=... python bench/accuracy/devlake/run.py --devlake-dir <folder with docker-compose.yml and .env> --out results.json
"""
import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
API = "http://localhost:8080"
TABLES = ("project_mapping", "pull_requests", "project_pr_metrics", "cicd_deployment_commits", "incidents",
          "project_incident_deployment_relationships")


def log(*a):
    print(datetime.now(timezone.utc).strftime("%H:%M:%S"), *a, flush=True)


def sh(cmd: list[str], cwd: Path | None = None) -> str:
    # Lenient decoding: one stray byte in a PR title once lost every table of a two-hour run.
    return subprocess.run(cmd, cwd=cwd, capture_output=True, encoding="utf-8", errors="replace", check=True).stdout


def unescape(v: str) -> str:
    # mysql --batch writes tabs, newlines and backslashes inside values as \t, \n and \\.
    return v.replace("\\t", "\t").replace("\\n", "\n").replace("\\\\", "\\") if "\\" in v else v


def call(c: httpx.Client, method: str, path: str, body=None):
    r = c.request(method, API + path, json=body)
    if r.status_code >= 400:
        raise RuntimeError(f"{method} {path}: {r.status_code} {r.text[:500]}")
    return r.json() if r.content else None


def footprint(folder: Path) -> dict:
    stats = sh(["docker", "stats", "--no-stream", "--format", "{{.Name}}\t{{.MemUsage}}"]).strip().splitlines()
    images = sh(["docker", "images", "--format", "{{.Repository}}:{{.Tag}}\t{{.Size}}"]).strip().splitlines()
    df = sh(["docker", "system", "df", "--format", "{{.Type}}\t{{.Size}}"]).strip().splitlines()
    return {"containers": stats, "images": images, "disk": df}


def devlake(folder: Path, repos: list[str], token: str, since: datetime) -> dict:
    out, t0 = {"stages": {}}, time.time()
    sh(["docker", "compose", "pull", "-q"], folder)
    out["stages"]["pull_s"] = round(time.time() - t0)
    t1 = time.time()
    sh(["docker", "compose", "up", "-d"], folder)
    c = httpx.Client(timeout=60)
    for _ in range(180):
        try:
            if c.get(API + "/plugins").status_code == 200:
                break
        except httpx.HTTPError:
            pass
        time.sleep(5)
    out["stages"]["start_s"] = round(time.time() - t1)
    log("DevLake up", out["stages"])
    t2, steps = time.time(), 0
    conn = call(c, "POST", "/plugins/github/connections", {"name": "h2h", "endpoint": "https://api.github.com/",
                                                          "authMethod": "AccessToken", "token": token, "rateLimitPerHour": 900,
                                                          "enableGraphql": True})
    steps += 1
    cid = conn["id"]
    cfg = call(c, "POST", f"/plugins/github/connections/{cid}/scope-configs", {
        "name": "h2h", "connectionId": cid, "entities": ["CROSS", "CODE", "CODEREVIEW", "CICD", "TICKET"],
        "deploymentPattern": "(deploy|push-image)", "productionPattern": "", "envNamePattern": "(?i)prod(.*)"})
    steps += 1
    gh = httpx.Client(timeout=30, headers={"Authorization": f"Bearer {token}"})
    scopes = []
    for full in repos:
        info = gh.get(f"https://api.github.com/repos/{full}").json()
        scopes.append({"githubId": info["id"], "connectionId": cid, "name": info["name"], "fullName": info["full_name"],
                       "htmlUrl": info["html_url"], "cloneUrl": info["clone_url"], "scopeConfigId": cfg["id"]})
    call(c, "PUT", f"/plugins/github/connections/{cid}/scopes", {"data": scopes})
    steps += 1
    call(c, "POST", "/projects", {"name": "h2h", "enable": True, "description": "",
                                  "metrics": [{"pluginName": "dora", "pluginOption": {}, "enable": True}]})
    steps += 1
    bp = call(c, "GET", "/projects/h2h")["blueprint"]
    call(c, "PATCH", f"/blueprints/{bp['id']}", {**bp, "timeAfter": since.strftime("%Y-%m-%dT%H:%M:%SZ"),
         "connections": [{"pluginName": "github", "connectionId": cid, "scopes": [{"scopeId": str(s["githubId"])} for s in scopes]}]})
    steps += 1
    pipe = call(c, "POST", f"/blueprints/{bp['id']}/trigger", {"skipCollectors": False, "fullSync": True})
    steps += 1
    out["stages"]["configure_s"], out["manual_steps"] = round(time.time() - t2), steps
    t3, status = time.time(), None
    while time.time() - t3 < 5 * 3600:
        p = call(c, "GET", f"/pipelines/{pipe['id']}")
        if p["status"] != status:
            status = p["status"]
            log("pipeline", status, p.get("finishedTasks"), "/", p.get("totalTasks"))
        if status in ("TASK_COMPLETED", "TASK_FAILED", "TASK_PARTIAL", "TASK_CANCELLED"):
            break
        time.sleep(30)
    out["stages"]["collect_s"], out["pipeline"] = round(time.time() - t3), {"status": status, "message": p.get("message")}
    out["footprint"] = footprint(folder)
    return out


def dump(folder: Path, dest: Path) -> dict:
    """DevLake's domain tables from its MySQL into JSON lines, for its DORA SQL (ported to DuckDB) to read."""
    dest.mkdir(parents=True, exist_ok=True)
    counts = {}
    for t in TABLES:
        try:
            raw = sh(["docker", "compose", "exec", "-T", "mysql", "mysql", "-umerico", "-pmerico", "lake", "--batch",
                      "--default-character-set=utf8mb4", "-e", f"SELECT * FROM {t}"], folder)
        except subprocess.CalledProcessError as exc:
            counts[t] = f"error: {(exc.stderr or '')[:300]}"
            log("dump failed", t, counts[t])
            continue
        lines = raw.split("\n")
        head = lines[0].split("\t") if lines and lines[0] else []
        rows = [dict(zip(head, [None if v == "NULL" else unescape(v) for v in line.split("\t")])) for line in lines[1:] if line]
        (dest / f"{t}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        counts[t] = len(rows)
        log("dumped", t, len(rows))
    return counts


def stackvitals(repos: list[str], days: int) -> dict:
    out = {}
    for full in repos:
        t0 = time.time()
        done = subprocess.run([sys.executable, "-m", "stackvitals", "delivery", full, "--days", str(days), "--json"],
                              capture_output=True, text=True)
        doc = json.loads(done.stdout) if done.returncode == 0 and done.stdout.strip().startswith("{") else None
        # `stackvitals delivery --json` nests the report under "delivery".
        rep = (doc or {}).get("delivery") or {}
        out[full] = {"seconds": round(time.time() - t0), "ok": doc is not None, "dora": rep.get("dora"),
                     "deploy_source": rep.get("deploy_source"), "error": None if doc else done.stderr[-400:]}
        log("stackvitals", full, out[full]["seconds"], "s", out[full]["ok"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--devlake-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=HERE / "results.json")
    args = ap.parse_args()
    picked = json.loads((HERE / "repos.json").read_text(encoding="utf-8"))
    repos, now = picked["drawn"], datetime.now(timezone.utc)
    since = now - timedelta(days=90)
    token = os.environ["GH_TOKEN"]
    res = {"run_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "repos": repos, "window": [since.isoformat()[:19], now.isoformat()[:19]]}
    try:
        res["devlake"] = devlake(args.devlake_dir, repos, token, since)
        res["devlake"]["tables"] = dump(args.devlake_dir, args.out.parent / "devlake-tables")
    except Exception as exc:  # noqa: BLE001 - the run still records what StackVitals did
        res["devlake_error"] = f"{type(exc).__name__}: {exc}"[:2000]
        log("DevLake error", res["devlake_error"])
    try:
        from stackvitals.core.export import panels
        res.setdefault("devlake", {})["dora_panels"] = {"h2h": panels(args.out.parent / "devlake-tables", since, now, "2023", "h2h")}
    except Exception as exc:  # noqa: BLE001 - scored again offline by score.py
        res["panels_error"] = f"{type(exc).__name__}: {exc}"[:2000]
        log("panels error", res["panels_error"])
    t0 = time.time()
    res["stackvitals"] = stackvitals(repos, 90)
    res["stackvitals_total_s"] = round(time.time() - t0)
    args.out.write_text(json.dumps(res, indent=1, default=str) + "\n", encoding="utf-8")
    log("written", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
