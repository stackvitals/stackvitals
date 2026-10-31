"""AI spend: what the organisation paid Anthropic, OpenAI and Cursor, read with one optional admin key each (shapes from
each provider's documented API), kept by day, and set beside the AI-involved pull requests merged in the same days."""
import json
from datetime import datetime, timezone

import httpx

from stackvitals.connectors import ai_spend
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
CFG = parse("")[0]


def bucket(day, *amounts):
    return {"starting_at": f"{day}T00:00:00Z", "ending_at": f"{day}T23:59:59Z",
            "results": [{"amount": a, "currency": "USD"} for a in amounts]}


def test_anthropic_cost_report_is_read_in_cents_by_day_across_pages(tmp_path):
    calls = []

    def handle(request):
        if request.url.path.endswith("/claude_code"):
            return httpx.Response(200, json={"data": [], "has_more": False, "next_page": None})
        calls.append(request)
        assert request.headers["x-api-key"] == "sk-ant-admin01-x" and request.headers["anthropic-version"] == "2023-06-01"
        page = request.url.params.get("page")
        if page is None:
            return httpx.Response(200, json={"data": [bucket("2026-10-01", "12345.5", "100"), bucket("2026-10-02")],
                                             "has_more": True, "next_page": "p2"})
        return httpx.Response(200, json={"data": [bucket("2026-10-03", "50")], "has_more": False, "next_page": None})
    store = ConnectorStore(tmp_path, "ai_spend")
    got = ai_spend.pull(store, {"STACKVITALS_ANTHROPIC_ADMIN_KEY": "sk-ant-admin01-x"}, CFG, NOW,
                        client=httpx.Client(transport=httpx.MockTransport(handle)))
    days = {r["day"]: r["usd"] for r in store.load()["day"] if r["src"] == "anthropic"}
    assert days == {"2026-10-01": 124.46, "2026-10-02": 0.0, "2026-10-03": 0.5} and got["complete"]
    assert calls[0].url.path == "/v1/organizations/cost_report" and calls[0].url.params["bucket_width"] == "1d"


def test_openai_costs_are_dollars_by_day(tmp_path):
    def handle(request):
        assert request.headers["authorization"] == "Bearer sk-admin-o" and request.url.path == "/v1/organization/costs"
        return httpx.Response(200, json={"object": "page", "has_more": False, "next_page": None, "data": [
            {"object": "bucket", "start_time": 1791072000, "end_time": 1791158400,
             "results": [{"object": "organization.costs.result", "amount": {"value": 3.25, "currency": "usd"}},
                         {"amount": {"value": 0.75, "currency": "usd"}}]}]})
    store = ConnectorStore(tmp_path, "ai_spend")
    ai_spend.pull(store, {"STACKVITALS_OPENAI_ADMIN_KEY": "sk-admin-o"}, CFG, NOW,
                  client=httpx.Client(transport=httpx.MockTransport(handle)))
    rows = [r for r in store.load()["day"] if r["src"] == "openai"]
    assert rows == [{"t": "day", "id": "openai:2026-10-04", "src": "openai", "day": "2026-10-04", "usd": 4.0}]


def test_cursor_spend_covers_the_billing_cycle_and_daily_use_counts_agents(tmp_path):
    def handle(request):
        assert request.headers["authorization"].startswith("Basic ")
        body = json.loads(request.content or b"{}")
        if request.url.path == "/teams/spend":
            return httpx.Response(200, json={"teamMemberSpend": [{"spendCents": 1200, "overallSpendCents": 5200},
                                                                 {"spendCents": 0, "overallSpendCents": 2000}],
                                             "subscriptionCycleStart": 1790812800000, "totalMembers": 2, "totalPages": 1})
        assert request.url.path == "/teams/daily-usage-data" and body["endDate"] > body["startDate"]
        return httpx.Response(200, json={"data": [
            {"date": 1791072000000, "agentRequests": 30, "acceptedLinesAdded": 400, "isActive": True},
            {"date": 1791072000000, "agentRequests": 12, "acceptedLinesAdded": 100, "isActive": True}]})
    store = ConnectorStore(tmp_path, "ai_spend")
    ai_spend.pull(store, {"STACKVITALS_CURSOR_ADMIN_KEY": "key_c"}, CFG, NOW,
                  client=httpx.Client(transport=httpx.MockTransport(handle)))
    got = store.load()
    cycle = [r for r in got["cycle"] if r["src"] == "cursor"][0]
    assert cycle["usd"] == 72.0 and cycle["members"] == 2 and cycle["start"] == "2026-10-01"
    use = [r for r in got["day"] if r["src"] == "cursor"][0]
    assert use["day"] == "2026-10-04" and use["agent_requests"] == 42 and use["accepted_lines"] == 500


def test_a_refused_admin_key_says_which_one(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(401)))
    try:
        ai_spend.pull(ConnectorStore(tmp_path, "ai_spend"), {"STACKVITALS_OPENAI_ADMIN_KEY": "bad"}, CFG, NOW, client=client)
    except ai_spend.ConnectorError as exc:
        assert "OpenAI refused the key (401)" in str(exc) and "bad" not in str(exc)
    else:
        raise AssertionError("expected a refusal")


def test_spend_is_summed_per_provider_and_set_beside_ai_involved_prs(tmp_path):
    store = ConnectorStore(tmp_path, "ai_spend")
    store.add([{"t": "day", "id": f"anthropic:2026-10-{d:02d}", "src": "anthropic", "day": f"2026-10-{d:02d}", "usd": 10.0}
               for d in range(1, 29)] + [{"t": "day", "id": "openai:2026-09-01", "src": "openai", "day": "2026-09-01", "usd": 99.0},
                                        {"t": "cycle", "id": "cursor:2026-10-01", "src": "cursor", "start": "2026-10-01",
                                         "usd": 72.0, "members": 2}], "2026-10-28")
    merged_ai = 40
    got = ai_spend.summary(tmp_path, NOW, merged_ai, window_days=30)
    assert got["providers"] == {"anthropic": 280.0, "cursor": 72.0} and got["total_usd"] == 352.0
    assert got["per_ai_pr_usd"] == 8.8 and got["ai_prs"] == 40 and got["window_days"] == 30
    assert ai_spend.summary(tmp_path / "none", NOW, 5) is None


def test_the_connection_check_reads_one_day_from_each_key_set_and_names_a_refusal():
    from stackvitals.connectors import check
    seen = []

    def handle(request):
        seen.append(request.url.host)
        if request.url.host == "api.openai.com":
            return httpx.Response(401)
        if request.url.host == "api.cursor.com":
            return httpx.Response(200, json={"teamMemberSpend": [], "totalMembers": 3})
        return httpx.Response(200, json={"data": [], "has_more": False})
    env = {"STACKVITALS_ANTHROPIC_ADMIN_KEY": "sk-ant-admin01-x", "STACKVITALS_CURSOR_ADMIN_KEY": "key_c"}
    client = httpx.Client(transport=httpx.MockTransport(handle))
    ok = check.check("ai_spend", CFG, env, client=client, now=NOW)
    assert ok["ok"] and "Anthropic" in ok["detail"] and "Cursor" in ok["detail"] and "OpenAI" not in ok["detail"]
    bad = check.check("ai_spend", CFG, {**env, "STACKVITALS_OPENAI_ADMIN_KEY": "sk-admin-bad"}, client=client, now=NOW)
    assert not bad["ok"] and "OpenAI refused the key (401)" in bad["detail"] and "sk-admin-bad" not in str(bad)
    assert check.configured("ai_spend", {"STACKVITALS_CURSOR_ADMIN_KEY": "k"}, CFG)
    assert check.resolve("all", CFG, env) and "ai_spend" in check.resolve("all", CFG, env)


def test_claude_code_analytics_are_summed_by_day_and_kept_apart_from_spend(tmp_path):
    def handle(request):
        if request.url.path.endswith("/cost_report"):
            return httpx.Response(200, json={"data": [bucket("2026-10-27", "1000")], "has_more": False, "next_page": None})
        assert request.url.path == "/v1/organizations/usage_report/claude_code"
        if request.url.params["starting_at"] != "2026-10-27":
            return httpx.Response(200, json={"data": [], "has_more": False, "next_page": None})
        rec = {"date": "2026-10-27T00:00:00Z", "actor": {"type": "user_actor", "email_address": "a@x.dev"},
               "core_metrics": {"num_sessions": 5, "lines_of_code": {"added": 100, "removed": 20}, "commits_by_claude_code": 3,
                                "pull_requests_by_claude_code": 1},
               "tool_actions": {"edit_tool": {"accepted": 9, "rejected": 1}, "write_tool": {"accepted": 0, "rejected": 0}},
               "model_breakdown": [{"model": "claude-opus-5-5", "estimated_cost": {"currency": "USD", "amount": 113}}]}
        return httpx.Response(200, json={"data": [rec, rec], "has_more": False, "next_page": None})
    store = ConnectorStore(tmp_path, "ai_spend")
    ai_spend.pull(store, {"STACKVITALS_ANTHROPIC_ADMIN_KEY": "k"}, CFG, NOW, client=httpx.Client(transport=httpx.MockTransport(handle)))
    day = [r for r in store.load()["day"] if r["src"] == "claude_code"]
    assert day == [{"t": "day", "id": "claude_code:2026-10-27", "src": "claude_code", "day": "2026-10-27", "sessions": 10,
                    "lines_added": 200, "lines_removed": 40, "commits": 6, "prs": 2, "accepted": 18, "rejected": 2, "users": 2,
                    "est_usd": 2.26}]
    got = ai_spend.summary(tmp_path, NOW, ai_prs=4)
    assert got["providers"] == {"anthropic": 10.0} and got["total_usd"] == 10.0
    assert got["tools"]["claude_code"] == {"sessions": 10, "lines_added": 200, "commits": 6, "prs": 2, "acceptance": 0.9, "est_usd": 2.26}
