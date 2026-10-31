"""Every surface gives the same numbers for the same inputs: the Action's published file, the CLI computing on a laptop
(through the service layer, reading the repo's own settings file), MCP and the page; MCP also says when and where from."""
import functools
import json
import subprocess
from datetime import datetime, timedelta, timezone

import anyio
import httpx
from mcp import Client

from mergescout.mcp_server import App
from stackvitals.ci.api import ActionsAPI
from stackvitals.core import delivery_report, deliverycli, services
from stackvitals.core.config import parse
from stackvitals.core.delivery_report import delivery_step
from stackvitals.core.workspace import run_job
from stackvitals.flow.store import FlowStore
from stackvitals.mcp_server import build_server

NOW = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
SETTINGS = '[delivery]\ndora_report = "2021"\n[identity]\nbots = ["release-captain"]\n'


def at(h):
    return (NOW - timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")


def pr(n, cr, mg, au="amy"):
    return {"t": "pr", "n": n, "ti": "Fix", "draft": False, "st": "MERGED", "cr": at(cr), "up": at(1), "mg": at(mg),
            "cl": at(mg), "au": au, "at": "User", "as": "MEMBER", "base": "main", "head": f"b{n}", "ho": au, "add": 30, "del": 5,
            "ev": [["review", at(cr - 3), "bob", "APPROVED", "MEMBER", "User", False]], "cm": [], "rq": [], "fa": at(cr + 2),
            "mc": f"m{n}", "lb": [], "ai": [], "cmn": 0}


PRS = [pr(100 + k, cr=24 * k + 30 + k, mg=24 * k + 2) for k in range(24)] + [pr(300, cr=50, mg=40, au="release-captain")]
REPO = {"default_branch": "main", "deployments": [],
        "releases": [{"tag": f"v{k}", "at": at(24 * 3 * k + 1), "pre": False, "sha": f"m{100 + 3 * k}"} for k in range(8)]}


def fake_github(published: dict | None):
    def handler(request):
        path = request.url.path
        if path == "/repos/o/r/contents/docs/delivery.json" and published is not None:
            return httpx.Response(200, content=json.dumps(published).encode())
        if path == "/repos/o/r/contents/.github/stackvitals.toml":
            return httpx.Response(200, content=SETTINGS.encode())
        return httpx.Response(404, json={"message": "Not Found"})
    return lambda token, repo, **kw: ActionsAPI(token, repo, client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                sleep=lambda s: None, **kw)


def test_the_action_the_cli_mcp_and_the_page_agree(tmp_path, monkeypatch, capsys):
    # The Action: Team Flow's history in the job's checkout, the repo's settings read once by CI Health.
    bare = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    env = {"GITHUB_REPOSITORY": "o/r", "STACKVITALS_TOKEN": "tok", "STACKVITALS_REMOTE": bare.as_uri(),
           "RUNNER_TEMP": str(tmp_path / "tmp")}

    def seed(ws):
        store = FlowStore(ws.path)
        store.put(PRS, "2026-10-19")
        store.save_repo(REPO)
        ws.cache["settings"] = parse(SETTINGS)[0]
        ws.results["Team Flow"] = {"prs": len(PRS)}
        return {}
    run_job(env, [("seed", seed), ("Delivery", lambda ws: delivery_step(ws, env, NOW))], NOW)
    published = json.loads(subprocess.run(["git", "show", "stackvitals-data:docs/delivery.json"], cwd=bare,
                                          capture_output=True, text=True).stdout)
    assert published["prs"] == 24 and published["dora"]["report"] == "2021"

    # The CLI on a laptop: the same PRs from its own copy, the settings file read from the repo, nothing published yet.
    home = tmp_path / "home"
    local = FlowStore(home / "flow" / "o__r")
    local.put(PRS, "2026-10-19")
    local.save_repo(REPO)
    monkeypatch.setattr(services, "local_stores", lambda *a, **k: ({"runs": [], "jobs": []}, local.load(), {}))
    from stackvitals.core import delivery_peers
    monkeypatch.setattr(delivery_peers, "load", lambda *a, **k: None)  # no benchmark download in tests
    computed = functools.partial(services.delivery, make_api=fake_github(None), now=NOW)
    monkeypatch.setattr(deliverycli.services, "delivery", computed)
    monkeypatch.setattr(deliverycli.ci_cli, "home", lambda: home)
    assert deliverycli.main(["o/r", "--json"], tok="tok") == 0
    cli = json.loads(capsys.readouterr().out)["delivery"]
    for key in ("prs", "phases", "dora", "sizes", "merge_frequency", "review_depth", "merged_without_review", "outliers"):
        assert cli[key] == published[key], key

    # MCP reads the published file, and says when and where its numbers come from.
    app = App(root=tmp_path / "mergescout", releases=None, live=None, log=lambda *a: None)
    server = build_server(app, ci_api=fake_github(published), ci_home=home, ci_token="tok")

    async def call():
        async with Client(server) as c:
            return json.loads((await c.call_tool("delivery_health", {"repo": "o/r"})).content[0].text)
    mcp = anyio.run(call)
    assert mcp["dora"] == published["dora"] and mcp["cycle_time"]["cycle"] == published["phases"]["cycle"]
    assert mcp["as_of"] == published["generated"] and mcp["sources"] == ["stackvitals-data branch"]

    # The page shows the same P75.
    page = delivery_report.render_html(published, "o/r")
    assert delivery_report._h(published["phases"]["pickup"]["p75_h"]) in page


def test_every_skill_names_only_tools_the_server_has(tmp_path):
    import re
    from pathlib import Path
    app = App(root=tmp_path / "mergescout", releases=None, live=None, log=lambda *a: None)
    server = build_server(app, ci_api=fake_github(None), ci_home=tmp_path / "home", ci_token="tok")

    async def names():
        async with Client(server) as c:
            return {t.name for t in (await c.list_tools()).tools}
    tools = anyio.run(names)
    skills = sorted((Path(__file__).resolve().parents[1] / "skills").glob("*/SKILL.md"))
    assert len(skills) >= 7
    for skill in skills:
        text = skill.read_text(encoding="utf-8")
        assert re.search(rf"^name: {skill.parent.name}$", text, re.M), skill
        named = set(re.findall(r"call `([a-z_]+)`", text))  # every skill names a tool as "call `tool`"
        assert named and named <= tools, (skill.parent.name, named - tools)
