from datetime import datetime, timezone

import httpx
import pytest

from mergescout.github.graphql import GitHubGraphQL, GraphQLError, NotFound

OK = {"data": {"rateLimit": {"cost": 3, "remaining": 4000, "resetAt": "2026-10-11T01:00:00Z"}, "x": 1}}
NOW = datetime(2026, 10, 11, 0, 0, 0, tzinfo=timezone.utc)


def make(responses, **kw):
    from mergescout.github.graphql import Gate
    queue = list(responses)
    client = httpx.Client(transport=httpx.MockTransport(lambda req: queue.pop(0)))
    sleeps, clock = [], [0.0]

    def sleep(seconds):
        # A fake sleep still moves time forward, as a real one does.
        sleeps.append(seconds)
        clock[0] += seconds
    kw.setdefault("gate", Gate(clock=lambda: clock[0]))
    gql = GitHubGraphQL("t", client=client, sleep=sleep, now=lambda: NOW, **kw)
    return gql, sleeps


def test_success_reports_cost():
    gql, sleeps = make([httpx.Response(200, json=OK)])
    r = gql.query("query { rateLimit { cost remaining resetAt } }")
    assert (r.cost, r.remaining, r.data["x"], sleeps) == (3, 4000, 1, [])


def test_retries_server_errors_with_backoff():
    gql, sleeps = make([httpx.Response(503), httpx.Response(503), httpx.Response(200, json=OK)])
    assert gql.query("q").cost == 3
    assert sleeps == [2, 4]


def test_gives_up_after_max_retries():
    gql, sleeps = make([httpx.Response(503)] * 3, max_retries=2)
    with pytest.raises(GraphQLError, match="kept failing"):
        gql.query("q")
    assert sleeps == [2, 4]


def test_not_found_and_other_errors():
    nf = {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "path": ["repository"], "message": "gone"}]}
    gql, _ = make([httpx.Response(200, json=nf)])
    with pytest.raises(NotFound):
        gql.query("q")
    bad = {"errors": [{"type": "SOMETHING", "message": "boom"}]}
    gql, _ = make([httpx.Response(200, json=bad)])
    with pytest.raises(GraphQLError, match="boom"):
        gql.query("q")


def test_query_without_rate_limit_field_is_a_bug():
    gql, _ = make([httpx.Response(200, json={"data": {"x": 1}})])
    with pytest.raises(ValueError, match="rateLimit"):
        gql.query("q")


def test_waits_for_reset_when_budget_runs_low():
    low = {"data": {"rateLimit": {"cost": 1, "remaining": 50, "resetAt": "2026-10-11T00:01:40Z"}}}
    gql, sleeps = make([httpx.Response(200, json=low)])
    gql.query("q")
    assert sleeps == [105.0]


def test_bad_token_message():
    gql, _ = make([httpx.Response(401, json={"message": "Bad credentials"})])
    with pytest.raises(GraphQLError, match="rejected the token"):
        gql.query("q")


def test_retries_500_and_wraps_non_json_body():
    gql, sleeps = make([httpx.Response(500), httpx.Response(200, json=OK)])
    assert gql.query("q").cost == 3
    assert sleeps == [2]
    gql, _ = make([httpx.Response(200, content=b"<html>oops</html>")])
    with pytest.raises(GraphQLError, match="not JSON"):
        gql.query("q")
    gql, _ = make([httpx.Response(418)])
    with pytest.raises(GraphQLError, match="HTTP 418"):
        gql.query("q")


def test_primary_limit_waits_until_reset_header():
    reset = str(int(NOW.timestamp()) + 90)
    limited = httpx.Response(403, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset},
                             json={"message": "API rate limit exceeded"})
    gql, sleeps = make([limited, httpx.Response(200, json=OK)])
    gql.query("q")
    assert sleeps == [95.0]


def test_secondary_limit_without_retry_after_waits_a_minute():
    limited = httpx.Response(403, json={"message": "You have exceeded a secondary rate limit"})
    gql, sleeps = make([limited, httpx.Response(200, json=OK)])
    gql.query("q")
    assert sleeps == [60]


def test_rate_limited_in_body_waits_until_reset_at():
    body = {"data": {"rateLimit": {"cost": 1, "remaining": 0, "resetAt": "2026-10-11T00:02:00Z"}},
            "errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]}
    gql, sleeps = make([httpx.Response(200, json=body), httpx.Response(200, json=OK)])
    gql.query("q")
    assert sleeps == [125.0]


def test_not_found_only_for_top_level_repository_path():
    nested = {"data": {"repository": {"x": None}},
              "errors": [{"type": "NOT_FOUND", "path": ["repository", "x"], "message": "missing field"}]}
    gql, _ = make([httpx.Response(200, json=nested)])
    with pytest.raises(GraphQLError) as excinfo:
        gql.query("q")
    assert not isinstance(excinfo.value, NotFound)
    top = {"data": {"repository": None},
           "errors": [{"type": "NOT_FOUND", "path": ["repository"], "message": "gone"}]}
    gql, _ = make([httpx.Response(200, json=top)])
    with pytest.raises(NotFound):
        gql.query("q")


def test_max_wait_raises_instead_of_sleeping_past_reset():
    from mergescout.github.graphql import RateLimited
    limited = {"data": {"rateLimit": {"cost": 1, "remaining": 0, "resetAt": "2026-10-11T00:50:00Z"}},
               "errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]}
    gql, sleeps = make([httpx.Response(200, json=limited)], max_wait=120)
    with pytest.raises(RateLimited):
        gql.query("q")
    assert sleeps == []


def test_max_wait_keeps_short_waits_and_skips_reserve_sleep():
    low = {"data": {"rateLimit": {"cost": 1, "remaining": 100, "resetAt": "2026-10-11T00:50:00Z"}}}
    limited = httpx.Response(403, headers={"retry-after": "30"}, json={"message": "secondary rate limit"})
    gql, sleeps = make([limited, httpx.Response(200, json=low)], max_wait=120)
    r = gql.query("q")
    assert (r.remaining, gql.last_remaining, sleeps) == (100, 100, [30])


def test_partial_keeps_data_when_only_nested_items_are_missing():
    body = {"data": {"rateLimit": {"cost": 1, "remaining": 4000, "resetAt": "2026-10-11T01:00:00Z"},
                     "repository": {"i1": {"number": 1}, "i2": None}},
            "errors": [{"type": "NOT_FOUND", "path": ["repository", "i2"], "message": "no issue 2"}]}
    gql, _ = make([httpx.Response(200, json=body)])
    r = gql.query("q", partial=True)
    assert r.data["repository"] == {"i1": {"number": 1}, "i2": None}
    gql, _ = make([httpx.Response(200, json=body)])
    with pytest.raises(GraphQLError, match="no issue 2"):
        gql.query("q")
    gone = {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "path": ["repository"], "message": "x"}]}
    gql, _ = make([httpx.Response(200, json=gone)])
    with pytest.raises(NotFound):
        gql.query("q", partial=True)


def test_gate_counts_requests_timeouts_and_waits():
    limited = httpx.Response(403, headers={"retry-after": "30"}, json={"message": "secondary rate limit"})
    gql, _ = make([limited, httpx.Response(504), httpx.Response(200, json=OK)])
    gql.query("q")
    gate = gql.gate
    assert gate.stats == {"requests": 3, "timeouts": 1, "rate_waits": 1, "waited_s": 34.0}
    assert gate.summary() == "requests=3 timeouts=1 rate-limit waits=1 waited=34s"


def test_a_request_that_cannot_be_sent_is_not_retried():
    def broken(req):
        raise httpx.LocalProtocolError("Illegal header value")
    sleeps = []
    gql = GitHubGraphQL("t", client=httpx.Client(transport=httpx.MockTransport(broken)), sleep=sleeps.append)
    with pytest.raises(GraphQLError, match="line breaks"):
        gql.query("q")
    assert sleeps == []
