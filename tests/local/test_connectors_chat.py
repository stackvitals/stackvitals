from datetime import datetime, timezone

import httpx

from stackvitals.connectors import discord, slack
from stackvitals.connectors.discourse import answers
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
TS = lambda iso: f"{datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp():.6f}"  # noqa: E731


def test_slack_threads_keep_when_the_team_first_replied_and_never_the_text(tmp_path):
    cfg = parse('[connectors.slack]\nchannels = ["C1"]\nteam = ["UTEAM"]\n')[0]
    a, b = TS("2026-10-20T10:00:00"), TS("2026-10-21T10:00:00")
    seen = []

    def handler(request):
        seen.append(request.headers.get("authorization"))
        if request.url.path.endswith("conversations.history"):
            return httpx.Response(200, json={"ok": True, "has_more": False, "messages": [
                {"ts": a, "user": "UASK", "text": "secret question", "reply_count": 2},
                {"ts": b, "user": "UTEAM", "text": "announcement"},
                {"ts": b + "1", "bot_id": "B1", "subtype": "bot_message", "text": "deploy done"}]})
        return httpx.Response(200, json={"ok": True, "messages": [
            {"ts": a, "user": "UASK"}, {"ts": TS("2026-10-20T11:00:00"), "user": "UPEER"},
            {"ts": TS("2026-10-20T13:00:00"), "user": "UTEAM", "text": "answer"}]})
    store = ConnectorStore(tmp_path, "slack")
    got = slack.pull(store, {"STACKVITALS_SLACK_TOKEN": "xoxb-1"}, cfg, NOW, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    rows = {r["id"]: r for r in store.load()["topic"]}
    first = rows[f"slack:C1:{a}"]
    assert got["read"] == 2 and first["first_reply"] == "2026-10-20T11:00:00Z" and first["first_team_reply"] == "2026-10-20T13:00:00Z"
    assert rows[f"slack:C1:{b}"]["by_team"] is True and set(seen) == {"Bearer xoxb-1"}
    assert "secret" not in str(rows) and "UASK" not in str(rows)
    assert answers(list(rows.values()), NOW)["median_hours"] == 3.0


def test_discord_replies_are_matched_to_the_message_they_answer(tmp_path):
    cfg = parse('[connectors.discord]\nchannels = ["111"]\nteam = ["900"]\n')[0]

    def handler(request):
        assert request.headers["authorization"] == "Bot tok"
        return httpx.Response(200, json=[
            {"id": "3", "timestamp": "2026-10-20T12:00:00+00:00", "author": {"id": "900"}, "content": "x",
             "message_reference": {"message_id": "1"}},
            {"id": "2", "timestamp": "2026-10-20T10:30:00+00:00", "author": {"id": "500"}, "content": "y",
             "message_reference": {"message_id": "1"}},
            {"id": "1", "timestamp": "2026-10-20T10:00:00+00:00", "author": {"id": "400"}, "content": "secret"},
            {"id": "4", "timestamp": "2026-10-20T10:05:00+00:00", "author": {"id": "77", "bot": True}, "content": "bot"}])
    store = ConnectorStore(tmp_path, "discord")
    discord.pull(store, {"STACKVITALS_DISCORD_TOKEN": "tok"}, cfg, NOW, client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    rows = {r["id"]: r for r in store.load()["topic"]}
    assert set(rows) == {"discord:111:1"}  # replies and bots aren't topics
    assert rows["discord:111:1"]["first_reply"] == "2026-10-20T10:30:00Z" and rows["discord:111:1"]["first_team_reply"] == "2026-10-20T12:00:00Z"
    assert "secret" not in str(rows) and "400" not in str(rows)


def test_a_channel_the_bot_cant_read_is_said_and_the_others_are_kept(tmp_path):
    # Review finding: one failing channel (or a limit mid-run) lost every channel's work read so far.
    cfg = parse('[connectors.discord]\nchannels = ["111", "222"]\nteam = ["900"]\n')[0]

    def handler(request):
        if "/222/" in request.url.path:
            return httpx.Response(403, json={})
        return httpx.Response(200, json=[{"id": "1", "timestamp": "2026-10-20T10:00:00+00:00", "author": {"id": "400"}}])
    store = ConnectorStore(tmp_path, "discord")
    got = discord.pull(store, {"STACKVITALS_DISCORD_TOKEN": "tok"}, cfg, NOW,
                       client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    assert set(r["id"] for r in store.load()["topic"]) == {"discord:111:1"} and "222" in got["note"] and got["complete"] is False
