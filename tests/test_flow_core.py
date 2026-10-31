"""The data branch as one job: one checkout and one commit for every module, overlapping runs that converge, a failing
module that never loses the others' work, retention and a size cap, an opt-in history squash that keeps every file
byte for byte, and a trigger that may be missed or repeated but never loses an event."""
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from ci_fake import T0, FakeGitHub, Run, job

from stackvitals.ci.action import run_action
from stackvitals.ci.api import ActionsAPI
from stackvitals.core.workspace import Workspace, run_job

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
ACTION_NOW = T0 + timedelta(days=2, hours=3)

def remote(tmp_path):
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    return bare


def show(bare, path):
    return subprocess.run(["git", "show", f"stackvitals-data:{path}"], cwd=bare, capture_output=True, text=True).stdout


def commits(bare):
    out = subprocess.run(["git", "rev-list", "--count", "stackvitals-data"], cwd=bare, capture_output=True, text=True).stdout
    return int(out.strip() or 0)


def env_for(tmp_path, bare):
    return {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
            "RUNNER_TEMP": str(tmp_path / "tmp")}


def writer(name, hooks):
    def step(ws: Workspace):
        (ws.path / f"{name}.txt").write_text(f"{name} data\n", encoding="utf-8")
        ws.after_commit(lambda: hooks.append(name), label=name)
        return {name: True}
    return step


def test_two_modules_share_one_checkout_and_one_commit_and_hooks_run_after_it(tmp_path):
    bare, hooks = remote(tmp_path), []
    out = run_job(env_for(tmp_path, bare), [("ci", writer("ci", hooks)), ("flow", writer("flow", hooks))], NOW)
    assert out["outcome"] == "pushed" and out["results"] == {"ci": {"ci": True}, "flow": {"flow": True}} and out["errors"] == {}
    assert commits(bare) == 1 and show(bare, "ci.txt") == "ci data\n" and show(bare, "flow.txt") == "flow data\n"
    assert hooks == ["ci", "flow"]
    again = run_job(env_for(tmp_path, bare), [("ci", writer("ci", hooks)), ("flow", writer("flow", hooks))], NOW)
    assert again["outcome"] == "unchanged" and commits(bare) == 1 and hooks == ["ci", "flow", "ci", "flow"]


def test_a_failing_step_does_not_lose_the_other_steps_work_and_is_reported(tmp_path):
    bare, hooks = remote(tmp_path), []

    def bad(ws):
        (ws.path / "half.txt").write_text("partial\n", encoding="utf-8")
        raise RuntimeError("GitHub said 502")
    out = run_job(env_for(tmp_path, bare), [("ci", writer("ci", hooks)), ("flow", bad)], NOW)
    assert out["outcome"] == "pushed" and "GitHub said 502" in out["errors"]["flow"] and out["results"] == {"ci": {"ci": True}}
    assert show(bare, "ci.txt") == "ci data\n" and show(bare, "half.txt") == "partial\n" and hooks == ["ci"]


def test_overlapping_runs_converge_without_losing_either_side(tmp_path):
    bare, hooks, seen = remote(tmp_path), [], []
    run_job(env_for(tmp_path, bare), [("ci", writer("ci", hooks))], NOW)

    def racing(ws):
        seen.append(1)
        if len(seen) == 1:
            # Another run pushes while this one works; the push is rejected and the steps run again on fresh data.
            run_job(env_for(tmp_path / "other", bare), [("other", writer("other", []))], NOW)
        (ws.path / "mine.txt").write_text(f"attempt {len(seen)}\n", encoding="utf-8")
        return {"attempts": len(seen)}
    out = run_job(env_for(tmp_path, bare), [("mine", racing)], NOW)
    assert out["outcome"] == "pushed" and out["results"]["mine"] == {"attempts": 2}
    assert show(bare, "other.txt") == "other data\n" and show(bare, "mine.txt") == "attempt 2\n" and show(bare, "ci.txt") == "ci data\n"


def test_a_hook_that_fails_is_noted_and_the_next_hooks_still_run(tmp_path):
    bare, hooks = remote(tmp_path), []

    def step(ws):
        (ws.path / "x.txt").write_text("x\n", encoding="utf-8")
        ws.after_commit(lambda: (_ for _ in ()).throw(OSError("chat down")), label="webhook")
        ws.after_commit(lambda: hooks.append("summary"), label="summary")
        return {}
    out = run_job(env_for(tmp_path, bare), [("ci", step)], NOW)
    assert hooks == ["summary"] and out["notes"] == ["webhook: chat down"]
    assert not Path(env_for(tmp_path, bare)["RUNNER_TEMP"]).exists() or not list(Path(env_for(tmp_path, bare)["RUNNER_TEMP"]).glob("stackvitals-*"))


def test_the_job_keeps_house_retention_cap_counter_and_an_opt_in_squash(tmp_path):
    import json
    from stackvitals.core.store import META, SQUASH_EVERY
    bare = remote(tmp_path)

    def seed(ws):
        for stream, day in (("ci/days", "2024-01-01"), ("ci/days", "2026-10-19"), ("flow/closed", "2026-10-18")):
            (ws.path / stream).mkdir(parents=True, exist_ok=True)
            (ws.path / stream / f"{day}.ndjson").write_text("x" * 3000 + "\n", encoding="utf-8")
        return {}
    env = env_for(tmp_path, bare) | {"STACKVITALS_SIZE_CAP_MB": "0.005"}  # about 5 KB: one of the two kept files must go
    out = run_job(env, [("seed", seed)], NOW)
    assert out["outcome"] == "pushed" and out["housekeeping"]["removed"] == {"ci/days": 1}
    assert out["housekeeping"]["dropped"] == ["flow/closed/2026-10-18.ndjson"]
    assert json.loads(show(bare, META))["commits"] == 1 and show(bare, "ci/days/2026-10-19.ndjson")
    # Squash is opt-in and waits for the counter; when it fires, the files stay the same and the history is one commit.
    out = run_job(env | {"STACKVITALS_SQUASH": "true"}, [("touch", lambda ws: (ws.path / "t.txt").write_text("1\n") or {})], NOW)
    assert commits(bare) == 2 and out["housekeeping"]["squashed"] is False

    def many(ws):
        meta = json.loads((ws.path / META).read_text(encoding="utf-8"))
        (ws.path / META).write_text(json.dumps({**meta, "commits": SQUASH_EVERY - 1}), encoding="utf-8")
        return {}
    out = run_job(env | {"STACKVITALS_SQUASH": "true"}, [("many", many)], NOW)
    assert out["housekeeping"]["squashed"] is True and commits(bare) == 1
    assert show(bare, "ci/days/2026-10-19.ndjson") == "x" * 3000 + "\n" and show(bare, "t.txt") == "1\n"
    assert json.loads(show(bare, META))["commits"] == 0


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout.strip()


def fake_api(runs):
    fake = FakeGitHub(runs)

    def handler(request):
        if request.url.path == "/repos/o/r":
            return httpx.Response(200, json={"default_branch": "main", "private": False})
        return fake.handle(request)
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def runs():
    return [Run(1, T0, [("failure", [job(11, "test", "failure", T0, 60)]),
                        ("success", [job(12, "test", "success", T0 + timedelta(minutes=10), 60, attempt=2)])]),
            Run(2, T0 + timedelta(days=1), [("success", [job(21, "test", "success", T0 + timedelta(days=1), 60)])])]


def ci_env(tmp_path, bare):
    return {**env_for(tmp_path, bare), "GITHUB_EVENT_NAME": "workflow_run"}


def data_json(bare):
    return json.loads(git("show", "stackvitals-data:docs/data.json", cwd=bare))


def test_the_same_event_processed_twice_changes_nothing(tmp_path):
    bare = remote(tmp_path)
    first = run_action(ci_env(tmp_path, bare), now=ACTION_NOW, make_api=fake_api(runs()), pr_comments=False)
    tree = git("rev-parse", "stackvitals-data^{tree}", cwd=bare)
    second = run_action(ci_env(tmp_path, bare), now=ACTION_NOW, make_api=fake_api(runs()), pr_comments=False)
    assert first["pushed"] and second["unchanged"] and git("rev-parse", "stackvitals-data^{tree}", cwd=bare) == tree
    assert git("rev-list", "--count", "stackvitals-data", cwd=bare) == "1"


def test_a_run_that_dies_before_its_commit_leaves_nothing_and_the_next_run_catches_up(tmp_path, monkeypatch):
    import stackvitals.ci.action as action
    bare = remote(tmp_path)
    real = action.write_outputs
    calls = []

    def dying(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise OSError("runner killed")
        return real(*args, **kwargs)
    monkeypatch.setattr(action, "write_outputs", dying)
    try:
        run_action(ci_env(tmp_path, bare), now=ACTION_NOW, make_api=fake_api(runs()), pr_comments=False)
    except OSError:
        pass
    assert git("rev-list", "--count", "stackvitals-data", cwd=bare) in ("", "0")  # nothing half-written reached the branch
    out = run_action(ci_env(tmp_path, bare), now=ACTION_NOW, make_api=fake_api(runs()), pr_comments=False)
    assert out["pushed"] and data_json(bare)["runs"] == 2


# Red CI on pull requests: real findings from the hand-check against GitHub's Checks API (pip, pytest, guidellm; 2026-10-20).
def _at(hours):
    return (NOW - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run(rid, sha, cr, c, att=1, ho="amy", br="fix", pr=()):
    return {"t": "run", "id": rid, "att": att, "wf": 1, "wfn": "CI", "path": ".github/workflows/ci.yml", "ev": "pull_request",
            "br": br, "sha": sha, "tree": sha, "pr": list(pr), "ho": ho, "c": c, "cr": _at(cr), "st": _at(cr), "up": _at(cr)}


def _job(jid, rid, name, c, en, start, att=1):
    return {"t": "job", "run": rid, "att": att, "id": jid, "n": name, "c": c, "cr": _at(start), "st": _at(start), "en": _at(en),
            "lb": [], "steps": []}


def _pr(n, cr, mg, ev=(), ho="amy", head="fix"):
    return {"t": "pr", "n": n, "st": "MERGED", "draft": False, "cr": _at(cr), "mg": _at(mg), "cl": _at(mg), "au": "amy",
            "at": "User", "as": "NONE", "head": head, "ho": ho, "ev": list(ev), "cm": []}


def test_red_ci_starts_at_the_first_failing_job_skips_summary_jobs_and_draft_time():
    from stackvitals.core.insights import red_intervals
    # pip #14324: red as soon as one job fails, although the run ends later; the "check" job that waits on all is not blamed.
    p = _pr(1, 30, 10)
    runs = [_run(10, "a", 29, "failure"), _run(11, "b", 27, "success")]
    jobs = [_job(100, 10, "tests / windows", "failure", 28.5, 28.9), _job(101, 10, "check", "failure", 26.5, 26.6),
            _job(110, 11, "tests / windows", "success", 25, 26)]
    waits = red_intervals(p, runs, jobs, {}, _at(0))
    assert [(w["from"], w["to"], w["ended_by"], w["failed"]["jobs"]) for w in waits] == \
        [(_at(28.5), _at(27), "push", ["tests / windows"])]
    # guidellm #1246: turned into a draft right after opening, red only while it was a draft: no red time.
    d = _pr(2, 40, 10, ev=[["draft", _at(39.9)], ["ready", _at(20)]])
    runs = [_run(20, "c", 39, "failure"), _run(21, "d", 25, "success")]
    jobs = [_job(200, 20, "tests", "failure", 38, 38.5), _job(210, 21, "tests", "success", 24, 24.5)]
    assert red_intervals(d, runs, jobs, {}, _at(0)) == []


def test_fork_runs_join_the_pr_that_was_open_on_that_branch_at_the_time():
    from stackvitals.core.joins import runs_by_pr
    prs = [_pr(1, 100, 90), _pr(2, 50, 40)]  # the same fork branch reused for a second PR
    runs = [_run(10, "a", 99, "failure"), _run(11, "b", 45, "success"), _run(12, "c", 70, "success"), _run(13, "d", 45, "success", pr=[2], ho=None)]
    found = runs_by_pr(runs, prs)
    assert [r["id"] for r in found[1]] == [10] and sorted(r["id"] for r in found[2]) == [11, 13]


def test_several_repos_query_as_one_and_load_into_postgres(tmp_path, capsys):
    # Real finding (2026-10-21): a repo whose cycle_s was all empty made DuckDB read it as JSON, and a cross-repo median
    # failed; summary columns now have fixed types. The Postgres DDL is checked by parsing, not by a server.
    import duckdb

    from stackvitals.core import export, sqlcli
    from stackvitals.core.summary import write_pr_summary
    t0 = "2026-10-01T00:00:00Z"

    def pr(n, merged):
        return {"n": n, "ti": "Fix", "draft": False, "st": "MERGED" if merged else "OPEN", "cr": t0, "up": t0,
                "mg": "2026-10-01T05:00:00Z" if merged else None, "cl": None, "au": "amy", "at": "User", "as": "MEMBER",
                "base": "main", "head": "b", "ho": "amy", "add": 1, "del": 1, "ev": [], "cm": [], "rq": [], "lb": []}
    write_pr_summary(tmp_path / "web", {"closed": [pr(1, True), pr(2, True)], "open": []}, NOW, "o/web")
    write_pr_summary(tmp_path / "api", {"closed": [], "open": [pr(3, False)]}, NOW, "o/api")
    query = "select repo, count(*) as prs, median(cycle_s) / 3600 as h from prs group by repo order by repo"
    assert sqlcli.main([query, "--dir", str(tmp_path / "web"), "--dir", str(tmp_path / "api"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [{"repo": "api", "prs": 1, "h": None}, {"repo": "web", "prs": 2, "h": 5.0}]
    ddl = export.postgres_ddl()
    con = duckdb.connect()
    for stmt in [s for s in ddl.split(";") if s.strip()]:
        con.execute(stmt)
    assert con.execute("select count(*) from information_schema.tables").fetchone()[0] == len(export.COLUMNS)


def test_settings_reach_every_step_on_every_run_and_an_unchanged_file_is_free(tmp_path):
    """Trust guard (P11 audit): settings were read only by CI Health, once a day, so a Flow-only job ran on defaults."""
    from stackvitals.core import settings
    seen, asked = [], []

    def handle(request):
        if not request.url.path.endswith("/contents/.github/stackvitals.toml"):
            return httpx.Response(404, json={"message": "Not Found"})
        asked.append(request.headers.get("if-none-match"))
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304, headers={"etag": '"v1"'})
        return httpx.Response(200, headers={"etag": '"v1"'}, content=b"[alerts]\npickup_p75_hours = 6\n")
    api = lambda tok, repo, **kw: ActionsAPI(tok, repo, client=httpx.Client(transport=httpx.MockTransport(handle)), **kw)
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}
    step = ("Delivery", lambda ws: seen.append(ws.cache["settings"]["alerts"]["pickup_p75_hours"]))
    run_job(env, [step], NOW, prepare=settings.prepare(env, make_api=api))
    again = run_job(env, [step], NOW, prepare=settings.prepare(env, make_api=api))
    assert seen == [6.0, 6.0] and asked == [None, '"v1"'] and again["outcome"] == "unchanged"


def test_every_setting_is_listed_once_and_the_reference_page_is_current():
    from stackvitals.core import config, schema

    def leaves(node, prefix=""):
        for key, value in node.items():
            path = f"{prefix}{key}"
            if path in ("ci.mute", "identity.aliases", "identity.teams", "investment.labels", "services", "rules") or not isinstance(value, dict):
                yield path
            else:
                yield from leaves(value, path + ".")
    assert set(leaves(config.DEFAULTS)) == set(schema.BY_KEY)
    assert (Path(__file__).resolve().parents[1] / "docs" / "settings.md").read_text(encoding="utf-8") == schema.markdown()


def test_pages_from_the_job_get_the_published_folder_only_when_it_changed(tmp_path):
    """P12 M2: the opt-in deploy steps get docs/ after a pushed run, nothing after a quiet one."""
    bare = remote(tmp_path)

    def page(ws, text="ci page"):
        (ws.path / "docs").mkdir(exist_ok=True)
        (ws.path / "docs" / "ci.html").write_text(text, encoding="utf-8")
        (ws.path / "summary").mkdir(exist_ok=True)
        (ws.path / "summary" / "manifest.json").write_text("{}", encoding="utf-8")
    first = run_job({**env_for(tmp_path, bare), "STACKVITALS_PAGES_DIR": str(tmp_path / "p1"), "STACKVITALS_PAGES_MODE": "deploy"},
                    [("CI Health", page)], NOW)
    # Published Pages get no download notes; the download (pages: artifact) gets them, localhost only, with Explore's tables.
    assert first["pages"] and (tmp_path / "p1" / "ci.html").exists() and not (tmp_path / "p1" / "OPEN-ME.txt").exists()
    again = run_job({**env_for(tmp_path, bare), "STACKVITALS_PAGES_DIR": str(tmp_path / "p2")}, [("CI Health", page)], NOW)
    assert not again["pages"] and not (tmp_path / "p2").exists()
    third = run_job({**env_for(tmp_path, bare), "STACKVITALS_PAGES_DIR": str(tmp_path / "p3"), "STACKVITALS_PAGES_MODE": "artifact"},
                    [("CI Health", lambda ws: page(ws, "changed"))], NOW)
    assert third["pages"] and "--bind 127.0.0.1" in (tmp_path / "p3" / "OPEN-ME.txt").read_text()
    assert (tmp_path / "p3" / "summary" / "manifest.json").exists()


def test_the_action_keeps_its_uv_cache_without_a_warning_on_every_users_run():
    # Fresh-install finding: setup-uv looked for dependency files in the user's empty folder and warned on every run.
    import yaml
    action = yaml.safe_load((Path(__file__).resolve().parents[1] / "action.yml").read_text(encoding="utf-8"))
    uv = next(s for s in action["runs"]["steps"] if "astral-sh/setup-uv@" in (s.get("uses") or ""))
    assert uv["with"].get("cache-dependency-glob") == "" and len(uv["uses"].split("@")[1]) == 40  # pinned to a commit


def test_the_privacy_page_names_every_outside_host_the_code_can_reach():
    # Trust groundwork (2026-10-23 review): a new outside host in the code must come with its line on docs/privacy.md.
    import re
    from stackvitals.core import dataflow
    root = Path(__file__).resolve().parents[1]
    assert (root / "docs" / "privacy.md").read_text(encoding="utf-8") == dataflow.markdown()
    known = dataflow.hosts() | dataflow.LINKS
    found = set()
    for path in (root / "src" / "stackvitals").rglob("*"):
        if path.suffix in (".py", ".js", ".html") and "vendor" not in path.parts:
            found |= set(re.findall(r"https://([a-zA-Z0-9.-]+\.[a-z]{2,})", path.read_text(encoding="utf-8", errors="replace")))
    assert sorted(found - known) == []


def test_the_install_page_shows_the_real_workflow_and_every_action_input():
    # Cold-install finding (2026-10-23): no doc showed the workflow file, the `uses:` line or the module ids.
    from stackvitals.core import installdoc
    root = Path(__file__).resolve().parents[1]
    action = (root / "action.yml").read_text(encoding="utf-8")
    assert (root / "docs" / "install.md").read_text(encoding="utf-8") == installdoc.markdown(action)


def test_every_action_is_pinned_to_a_commit():
    # Supply chain (Phase 18): a moved tag can't swap the code a workflow runs; our own Action is the only exception.
    import re
    from stackvitals.ci.cli import ACTION_REF, workflow_template
    from stackvitals.portal.cli import WORKFLOW as PORTAL
    root = Path(__file__).resolve().parents[1]
    # Every YAML file under .github and deploy (workflows, composite actions, .yaml too), not just today's ones.
    texts = {str(p.relative_to(root)): p.read_text(encoding="utf-8")
             for p in [root / "action.yml", *(root / ".github").rglob("*.y*ml"), *(root / "deploy").rglob("*.y*ml")]}
    texts["template"], texts["portal template"] = workflow_template(), PORTAL.format(ref=ACTION_REF)
    found = [(name, m.strip("'\"")) for name, text in texts.items()
             for m in re.findall(r"""(?<![\w-])["']?uses["']?\s*:\s*([^\s#,}]+)""", text)]
    loose = [(name, m) for name, m in found
             if m != ACTION_REF and not m.startswith("./") and not re.search(r"@[0-9a-f]{40}$", m)]
    assert len(found) >= 20 and loose == []


def test_the_threat_model_names_only_tests_that_exist():
    # Docs drift (Phase 18): each threat and failure mode names the committed test guarding it; a renamed test fails here.
    import re
    root = Path(__file__).resolve().parents[1]
    defined = {m for p in (root / "tests").glob("test_flow_*.py")
               for m in re.findall(r"^def (test_[a-z0-9_]+)", p.read_text(encoding="utf-8"), re.M)}
    for doc, least in (("threat-model.md", 20), ("limitations.md", 10)):
        named = set(re.findall(r"`(test_[a-z0-9_]+)`", (root / "docs" / doc).read_text(encoding="utf-8")))
        assert len(named) >= least and sorted(named - defined) == [], doc


def test_every_link_between_the_docs_reaches_a_file_and_heading():
    # Docs drift (Phase 18): the README's module sections moved to docs/modules.md; a moved file or heading fails here.
    import re
    root = Path(__file__).resolve().parents[1]
    pages = [*(root / "docs").rglob("*.md"), *(root / n for n in ("README.md", "CONTRIBUTING.md", "GOVERNANCE.md", "SECURITY.md"))]

    def anchors(page):
        return {re.sub(r"[^\w\- ]", "", h.strip().lower()).replace(" ", "-")
                for h in re.findall(r"^#+ (.*)$", page.read_text(encoding="utf-8"), re.M)}
    broken = []
    for page in pages:
        for url in re.findall(r"\]\(([^)\s]+)\)", page.read_text(encoding="utf-8")):
            if url.startswith(("http:", "https:", "mailto:")):
                continue
            path, _, anchor = url.partition("#")
            target = (page.parent / path) if path else page
            if not target.exists() or (anchor and target.suffix == ".md" and anchor not in anchors(target)):
                broken.append(f"{page.relative_to(root)} -> {url}")
    assert broken == []


def test_the_action_installs_its_locked_dependencies():
    # Security review (Phase 18): `uvx --from` ignored uv.lock, so each run ran whatever PyPI had that day with the token.
    root = Path(__file__).resolve().parents[1]
    action = (root / "action.yml").read_text(encoding="utf-8")
    assert "uv run --quiet --frozen --only-group action --project \"$GITHUB_ACTION_PATH\" python -m stackvitals action" in action
    assert "uvx" not in action and (root / "uv.lock").exists()
    # The Action's group is the base dependencies without the MCP server's, so it can't drift from what the code needs.
    import tomllib
    meta = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    assert sorted(meta["dependency-groups"]["action"]) == sorted(d for d in meta["project"]["dependencies"] if not d.startswith("mcp"))


def test_releases_build_read_only_and_sign_in_a_separate_job():
    # Security review (Phase 18): signing rights sat beside an unpinned build backend and a stored write token.
    import yaml
    root = Path(__file__).resolve().parents[1]
    flow = yaml.safe_load((root / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))
    build, publish = flow["jobs"]["build"], flow["jobs"]["publish"]
    assert flow["permissions"] == {} and build["permissions"] == {"contents": "read"}
    steps = "\n".join(str(s) for s in build["steps"])
    assert "'persist-credentials': False" in steps and "--build-constraint .github/build-constraints.txt" in steps
    assert "hatchling==" in (root / ".github" / "build-constraints.txt").read_text(encoding="utf-8")
    assert publish["needs"] == "build" and publish["environment"] == "release" and "id-token" in publish["permissions"]


def test_no_workflow_uses_pull_request_target():
    # Review (Phase 19): that trigger runs with the base repo's token and secrets on a fork's pull request.
    from stackvitals.ci.cli import ACTION_REF, workflow_template
    from stackvitals.portal.cli import WORKFLOW as PORTAL
    root = Path(__file__).resolve().parents[1]
    texts = [workflow_template(), PORTAL.format(ref=ACTION_REF), (root / "action.yml").read_text(encoding="utf-8"),
             *(p.read_text(encoding="utf-8") for p in [*(root / ".github").rglob("*.y*ml"), *(root / "deploy").rglob("*.y*ml")])]
    assert not any("pull_request_target:" in t or "pull_request_target]" in t for t in texts)


def test_one_module_can_be_installed_alone_with_only_the_permissions_it_uses():
    # Review (Phase 19): adopt one module at a time; a file for Dependencies alone shouldn't ask to read Actions.
    from itertools import combinations

    import yaml

    from stackvitals.ci.cli import MODULES, workflow_template
    for n in range(1, len(MODULES) + 1):
        for mods in combinations(MODULES, n):
            d, has = yaml.safe_load(workflow_template(modules=mods)), set(mods)
            assert d["jobs"]["vitals"]["steps"][0]["with"]["modules"] == ",".join(mods)
            assert ("workflow_run" in d[True]) == ("ci" in has) and ("pull_request" in d[True]) == ("deps" in has)
            assert ("actions" in d["permissions"]) == ("ci" in has) and ("deployments" in d["permissions"]) == ("flow" in has)
            assert d["permissions"]["pull-requests"] == ("write" if has & {"ci", "flow"} else "read")


def test_history_in_a_bucket_converges_like_the_branch_and_signs_requests_as_aws_does(tmp_path):
    # Phase 19: storage outside git for busy orgs; a run that lost the race must start again, never overwrite.
    from datetime import datetime, timezone

    import httpx

    from stackvitals.core import bucket
    h = bucket.sign("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"}, bucket.EMPTY,
                    "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1", datetime(2013, 5, 24, tzinfo=timezone.utc))
    assert h["authorization"].endswith("f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")  # AWS's own example
    objects = {}

    def s3(request):
        key = request.url.path.split("/", 2)[2]
        if request.method == "GET":
            return httpx.Response(200, content=objects[key][0], headers={"etag": objects[key][1]}) if key in objects else httpx.Response(404)
        if request.method == "DELETE":
            objects.pop(key, None)
            return httpx.Response(204)
        cur = objects.get(key)
        if ("if-none-match" in request.headers and cur) or ("if-match" in request.headers and (not cur or cur[1] != request.headers["if-match"])):
            return httpx.Response(412)
        objects[key] = (request.content, f'"{len(objects)}-{len(request.content)}"')
        return httpx.Response(200, headers={"etag": objects[key][1]})
    mk = lambda n: bucket.BucketStore("s3://b/p", tmp_path / n, "https://s3.example.com", "k", "s", "auto",  # noqa: E731
                                      client=httpx.Client(transport=httpx.MockTransport(s3)))
    a, b = mk("a"), mk("b")
    a.open(), b.open()
    (a.path / "f").write_text("a", encoding="utf-8")
    (b.path / "f").write_text("b", encoding="utf-8")
    assert a.commit_push("a") == "pushed" and b.commit_push("b") == "rejected"
    b.open()
    assert (b.path / "f").read_text(encoding="utf-8") == "a"
    # The loser's upload stays: a run still working may have uploaded the same content and be about to publish it.
    c = mk("c")
    c.open()
    (c.path / "f").write_text("b", encoding="utf-8")
    assert c.commit_push("c") == "pushed"
    c.open()
    assert (c.path / "f").read_text(encoding="utf-8") == "b"


def test_sql_over_a_remote_data_branch_cannot_inject_or_touch_files(tmp_path, capsys):
    # Audit finding (2026-10-31): manifest names from a remote branch went unescaped into file and table names.
    from stackvitals.core import sqlcli
    files = {"prs.jsonl": b'{"number": 1}\n', 'x"; COPY (SELECT 1) TO \'pwn.csv\'; --.jsonl': b"{}\n", "../up.jsonl": b"{}\n"}

    class Api:
        def __init__(self, token, repo, **kw):
            pass

        def file(self, path, ref):
            return json.dumps({"files": {n: {} for n in files}}).encode() if path.endswith("manifest.json") else files[path[8:]]
    assert sqlcli.main(["--repo", "o/r", "--json", "select count(*) as n from prs"], make_api=Api, tok="t") == 0
    out = capsys.readouterr()
    assert json.loads(out.out) == [{"n": 1}] and out.err.count("Skipped") == 2
    assert sqlcli.main(["--repo", "o/r", f"copy prs to '{tmp_path.as_posix()}/out.csv'"], make_api=Api, tok="t") == 1
    assert not (tmp_path / "out.csv").exists()
