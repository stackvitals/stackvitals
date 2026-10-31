"""Delivery on every surface: the Action writes the page and file from the job's checkout, the CLI and MCP read the
published file or compute from this machine's copies, and the text never lets PR titles or names ping or link anyone."""
import json
import subprocess
from datetime import timedelta

import httpx

from stackvitals.ci.api import ActionsAPI
from stackvitals.core import delivery_report, services
from stackvitals.core.config import parse
from stackvitals.core.delivery import build
from stackvitals.core.workspace import run_job
from stackvitals.flow.store import FlowStore
from test_core_delivery import NOW, at, pr, review

CFG = parse("")[0]


def sample():
    merged = [pr(100 + k, cr=200 + k, mg=150 + k, fa=210 + k, ev=[review(190 + k)]) for k in range(12)]
    merged.append(pr(50, cr=60, mg=55, fa=61, ti='Revert "Add <script>cache</script>"', ev=[review(58)]))
    repo = {"default_branch": "main", "deployments": [], "releases": [{"tag": "v1", "at": at(140), "pre": False, "sha": "r"},
                                                                       {"tag": "v2", "at": at(50), "pre": False, "sha": "s"}]}
    opened = [pr(1, cr=24 * 40, ev=[["req", at(24 * 39), "bob"]], rq=["bob"])]
    return {"closed": merged, "open": opened}, repo


def test_the_page_and_summary_show_phases_dora_stuck_prs_and_sources_safely():
    flow, repo = sample()
    out = build(flow, repo, {"runs": [], "jobs": []}, [], NOW, 90, CFG)
    page = delivery_report.render_html(out, "o/r")
    assert "Cycle time" in page and "Pickup" in page and "P75" in page and "n=13" in page
    assert "Deployment frequency" in page and "releases" in page and "2023" in page
    assert "Hanging review" in page and "https://github.com/o/r/pull/1" in page
    assert "<script>cache" not in page
    md = delivery_report.render_markdown(out, "o/r")
    assert "Delivery" in md and "lead time" in md.lower() and "@" not in md


def test_the_action_step_writes_the_delivery_page_from_the_checkout(tmp_path):
    from stackvitals.core.delivery_report import delivery_step
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp"), "GITHUB_STEP_SUMMARY": str(tmp_path / "s.md")}
    flow, repo = sample()

    def seed(ws):
        store = FlowStore(ws.path)
        store.put(flow["closed"], "2026-10-16")
        store.save_open({p["n"]: p for p in flow["open"]})
        store.save_repo(repo)
        ws.results["Team Flow"] = {"prs": 1}
        return {}
    out = run_job(env, [("seed", seed), ("Delivery", lambda ws: delivery_step(ws, env, NOW))], NOW)
    assert out["errors"] == {} and out["results"]["Delivery"]["prs"] == 13
    shown = subprocess.run(["git", "show", "stackvitals-data:docs/delivery.json"], cwd=bare, capture_output=True, text=True).stdout
    data = json.loads(shown)
    assert data["schema"] == 1 and data["deploy_source"] == "releases" and data["phases"]["pickup"]["n"] == 13
    assert subprocess.run(["git", "show", "stackvitals-data:docs/delivery.html"], cwd=bare, capture_output=True).returncode == 0
    assert "Delivery" in (tmp_path / "s.md").read_text(encoding="utf-8")
    # DevLake's tables sit beside the other summaries, so DevLake's SQL runs on them in the browser or `stackvitals sql`.
    metrics = subprocess.run(["git", "show", "stackvitals-data:summary/devlake_project_pr_metrics.jsonl"], cwd=bare,
                             capture_output=True, text=True).stdout.splitlines()
    assert len(metrics) == 13 and json.loads(metrics[0])["project_name"] == "o/r"
    manifest = json.loads(subprocess.run(["git", "show", "stackvitals-data:summary/manifest.json"], cwd=bare,
                                         capture_output=True, text=True).stdout)
    assert "devlake_cicd_deployment_commits.jsonl" in manifest["files"]


def test_the_service_reads_the_published_file_first(tmp_path):
    flow, repo = sample()
    published = {"schema": 1, **build(flow, repo, {"runs": [], "jobs": []}, [], NOW, 90, CFG)}

    def handler(request):
        if request.url.path == "/repos/o/r/contents/docs/delivery.json":
            return httpx.Response(200, content=json.dumps(published).encode())
        return httpx.Response(404, json={"message": "Not Found"})
    make = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),  # noqa: E731
                                                sleep=lambda s: None, **kw)
    out, source = services.delivery("o/r", 90, "tok", tmp_path, make_api=make)
    assert out["prs"] == 13 and source == "stackvitals-data branch"


def test_the_cli_prints_delivery_or_its_json(monkeypatch, capsys):
    from stackvitals.core import deliverycli
    flow, repo = sample()
    result = build(flow, repo, {"runs": [], "jobs": []}, [], NOW, 90, CFG)
    monkeypatch.setattr(deliverycli.services, "delivery", lambda repo, days, tok, home, **kw: (result, "read live"))
    assert deliverycli.main(["o/r"], tok="tok") == 0
    assert "Pickup" in capsys.readouterr().out
    assert deliverycli.main(["o/r", "--json"], tok="tok") == 0
    assert json.loads(capsys.readouterr().out)["delivery"]["prs"] == 13


def test_the_page_shows_teams_and_owning_teams_and_says_when_there_is_too_little_data():
    flow, repo = sample()
    for p in flow["closed"]:
        p["paths"] = ["web/a.js"]
    cfg = parse('[identity.teams]\nweb = ["amy"]\n')[0]
    out = build(flow, {**repo, "codeowners": "/web/ @o/web-team\n"}, {"runs": [], "jobs": []}, [], NOW, 90, cfg)
    page = delivery_report.render_html(out, "o/r")
    assert "By team" in page and "By owning team" in page and "@o/web-team" in page
    few = build({"closed": flow["closed"][:3], "open": []}, repo, {"runs": [], "jobs": []}, [], NOW, 90, CFG)
    assert "not enough data" in delivery_report.render_html(few, "o/r")


def test_a_run_with_nothing_new_leaves_the_delivery_files_alone(tmp_path):
    from stackvitals.core.delivery_report import delivery_step
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    flow, repo = sample()

    def seed(ws):
        ws.results["Team Flow"] = {"prs": 1}
        if (ws.path / "flow" / "closed").is_dir():
            return {}
        store = FlowStore(ws.path)
        store.put(flow["closed"], "2026-10-16")
        store.save_open({p["n"]: p for p in flow["open"]})
        store.save_repo(repo)
        ws.results["Team Flow"] = {"prs": 1}
        return {}
    run_job(env, [("seed", seed), ("Delivery", lambda ws: delivery_step(ws, env, NOW))], NOW)
    first = subprocess.run(["git", "rev-parse", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout
    later = NOW + timedelta(minutes=30)  # the same data half an hour on: only the clock and the waits moved
    run_job(env, [("seed", seed), ("Delivery", lambda ws: delivery_step(ws, env, later))], later)
    assert subprocess.run(["git", "rev-parse", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout == first


def test_a_guessed_deployment_source_is_called_a_guess_with_what_was_counted_and_the_fix():
    runs = [{"id": i, "att": 1, "wfn": "CD deploy main", "path": ".github/workflows/cd.yml", "ev": "push", "br": "main",
             "sha": f"s{i}", "c": "success", "up": at(50 - i)} for i in range(1, 6)]
    out = build({"closed": [], "open": []}, {"default_branch": "main", "deployments": [], "releases": []}, {"runs": runs},
                [], NOW, 90, CFG)
    page = delivery_report.render_html(out, "o/r")
    assert "a guess from workflow names" in page and "CD deploy main (5)" in page and 'source = "releases"' in page


def test_the_page_says_which_permission_reads_deployments_when_the_token_could_not():
    out = build({"closed": [], "open": []}, {"default_branch": "main", "deployments": [], "releases": [], "no_deployments": True},
                {"runs": []}, [], NOW, 90, CFG)
    assert out["deployments_unreadable"] is True
    assert "deployments: read" in delivery_report.render_html(out, "o/r")


def test_opted_in_stuck_prs_get_a_label_that_comes_off_once_they_move(tmp_path):
    from stackvitals.core.delivery_report import STUCK_LABEL, delivery_step
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    flow, repo = sample()
    flow["open"].append(pr(2, cr=24 * 2, lb=[STUCK_LABEL]))  # labelled before, no longer waiting on a review
    calls = []

    def gh(request):
        calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        return httpx.Response(200, json=[])
    make = lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(gh)),  # noqa: E731
                                                sleep=lambda s: None, **kw)

    def seed(ws):
        store = FlowStore(ws.path)
        store.put(flow["closed"], "2026-10-16")
        store.save_open({p["n"]: p for p in flow["open"]})
        store.save_repo(repo)
        ws.results["Team Flow"] = {"prs": 1}
        return {}
    out = run_job(env, [("seed", seed), ("Delivery", lambda ws: delivery_step(ws, env, NOW, label_stuck=True, make_api=make))], NOW)
    assert out["errors"] == {} and out["results"]["Delivery"]["labelled"] == {"added": 1, "removed": 1}
    assert ("POST", "/repos/o/r/issues/1/labels", {"labels": [STUCK_LABEL]}) in calls
    assert any(c[0] == "DELETE" and c[1].startswith("/repos/o/r/issues/2/labels/") for c in calls)
    # Without the opt-in nothing is touched.
    calls.clear()
    run_job(env, [("Delivery", lambda ws: delivery_step(ws, {**env}, NOW, make_api=make))], NOW)
    assert calls == []


def test_the_page_compares_with_similar_public_repos_and_says_what_the_comparison_cannot_see(tmp_path, monkeypatch):
    from stackvitals.core.delivery_report import delivery_step
    from test_core_delivery_peers import BENCH, merged_prs
    bench = tmp_path / "delivery-benchmarks.json"
    bench.write_text(json.dumps(BENCH), encoding="utf-8")
    monkeypatch.setenv("STACKVITALS_DELIVERY_BENCH_URL", str(bench))
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}

    def seed(ws):
        store = FlowStore(ws.path)
        store.put(merged_prs(40), "2026-10-16")
        store.save_repo({"default_branch": "main", "language": "Python", "stars": 2500, "releases": [], "deployments": []})
        ws.results["Team Flow"] = {"prs": 12}
        return {}
    run_job(env, [("seed", seed), ("Delivery", lambda ws: delivery_step(ws, env, NOW))], NOW)
    data = json.loads(subprocess.run(["git", "show", "stackvitals-data:docs/delivery.json"], cwd=bare, capture_output=True,
                                     text=True).stdout)
    assert data["peers"]["group"] == "Python repos with 1k-10k stars"
    page = subprocess.run(["git", "show", "stackvitals-data:docs/delivery.html"], cwd=bare, capture_output=True, text=True).stdout
    assert "Compared with similar public repos" in page and "8.9" in page and "22%" in page and "no private teams" in page
