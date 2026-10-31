from datetime import datetime, timezone

import httpx

from stackvitals.connectors import discourse
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core.config import parse

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
CFG = parse('[connectors.discourse]\nurl = "https://discuss.example.org"\nteam = ["core-dev"]\n')[0]


def post(n, user, at, staff=False, group=None):
    return {"post_number": n, "username": user, "created_at": at, "staff": staff, "primary_group_name": group,
            "cooked": "<p>secret text</p>"}


TOPICS = {1: [post(1, "asker", "2026-10-10T10:00:00.000Z"), post(2, "peer", "2026-10-10T11:00:00.000Z"),
              post(3, "mod", "2026-10-11T10:00:00.000Z", staff=True)],
          2: [post(1, "asker2", "2026-10-12T10:00:00.000Z"), {**post(2, "system", "2026-10-12T10:01:00.000Z", staff=True),
                                                               "post_type": 3},
              post(3, "core-dev", "2026-10-12T14:00:00.000Z")],
          3: [post(1, "mod", "2026-10-13T10:00:00.000Z", staff=True)],
          4: [post(1, "old", "2026-01-01T10:00:00.000Z")]}


def handler(request):
    path = request.url.path
    if path == "/latest.json":
        page = int(request.url.params.get("page", 0))
        rows = [{"id": i, "created_at": TOPICS[i][0]["created_at"], "last_posted_at": TOPICS[i][-1]["created_at"],
                 "posts_count": len(TOPICS[i]), "closed": False, "has_accepted_answer": i == 2, "title": "Help me"}
                for i in (3, 2, 1, 4)] if page == 0 else []
        return httpx.Response(200, json={"topic_list": {"topics": rows, "more_topics_url": None}})
    if path.startswith("/t/"):
        tid = int(path.split("/")[2].split(".")[0])
        return httpx.Response(200, json={"id": tid, "post_stream": {"posts": TOPICS[tid]}})
    return httpx.Response(404)


def test_topics_are_kept_with_when_the_team_first_replied_and_never_their_text(tmp_path):
    store = ConnectorStore(tmp_path, "discourse")
    client = httpx.Client(base_url="https://discuss.example.org", transport=httpx.MockTransport(handler))
    got = discourse.pull(store, {}, CFG, NOW, client=client, sleep=lambda s: None)
    topics = {r["id"]: r for r in store.load()["topic"]}
    assert got["read"] == 3 and set(topics) == {"discourse:1", "discourse:2", "discourse:3"}  # the old one is out
    assert topics["discourse:1"]["first_team_reply"] == "2026-10-11T10:00:00Z" and topics["discourse:1"]["first_reply"] == "2026-10-10T11:00:00Z"
    assert topics["discourse:2"]["first_team_reply"] == "2026-10-12T14:00:00Z" and topics["discourse:2"]["solved"] is True
    assert topics["discourse:3"]["by_team"] is True
    text = str(store.load())
    assert "secret" not in text and "asker" not in text and "Help me" not in text


def test_the_forum_url_must_be_https_and_the_answer_stats_follow_the_project_rule(tmp_path):
    assert parse('[connectors.discourse]\nurl = "http://x.org"\n')[0]["connectors"]["discourse"]["url"] == ""
    store = ConnectorStore(tmp_path, "discourse")
    client = httpx.Client(base_url="https://discuss.example.org", transport=httpx.MockTransport(handler))
    discourse.pull(store, {}, CFG, NOW, client=client, sleep=lambda s: None)
    out = discourse.answers(store.load()["topic"], NOW)
    # Two outside topics: answered by the team after 24 and 4 hours.
    assert out["topics"] == 2 and out["median_hours"] == 14.0 and out["solved_share"] == 0.5
