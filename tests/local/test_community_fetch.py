import json
from datetime import datetime, timedelta, timezone

import httpx

from stackvitals.ci.api import ActionsAPI
from stackvitals.community.collect import collect_stars, collect_traffic

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
WEEK = 604800


def api_for(handler, calls):
    def wrapped(request):
        calls.append((request.url.path, dict(request.url.params)))
        return handler(request)
    return ActionsAPI("t", "o/r", client=httpx.Client(transport=httpx.MockTransport(wrapped)), sleep=lambda s: None)


def history(total_weeks):
    start = int(NOW.timestamp()) // WEEK * WEEK
    rows = [{"week": start - i * WEEK, "total": i % 7, "days": []} for i in range(total_weeks)]

    def handler(request):
        page = int(request.url.params.get("page", 1))
        return httpx.Response(200, json=rows[(page - 1) * 30: page * 30])
    return handler


def test_star_history_is_read_whole_once_then_only_the_newest_page_once_a_day(tmp_path):
    calls = []
    out = collect_stars(api_for(history(75), calls), tmp_path, NOW)
    assert out == {"requests": 3, "weeks": 75} and len(json.loads((tmp_path / "stars.json").read_text())["weeks"]) == 75
    calls.clear()
    assert collect_stars(api_for(history(75), calls), tmp_path, NOW + timedelta(hours=3))["requests"] == 0
    out = collect_stars(api_for(history(76), calls), tmp_path, NOW + timedelta(days=1))
    assert out["requests"] == 1 and calls[0][1]["page"] == "1"


def traffic_handler(views, referrers):
    def handler(request):
        path = request.url.path
        if path.endswith("/traffic/views") or path.endswith("/traffic/clones"):
            key = "views" if "views" in path else "clones"
            return httpx.Response(200, json={key: [{"timestamp": f"{d}T00:00:00Z", "count": c, "uniques": u}
                                                   for d, c, u in views]})
        if path.endswith("/popular/referrers"):
            return httpx.Response(200, json=[{"referrer": r, "count": c, "uniques": 1} for r, c in referrers])
        return httpx.Response(200, json=[{"path": "/o/r", "title": "o/r: a title anyone can set", "count": 9, "uniques": 3}])
    return handler


def test_traffic_days_are_kept_past_githubs_14_days_and_today_is_updated(tmp_path):
    calls = []
    collect_traffic(api_for(traffic_handler([("2026-10-05", 10, 4), ("2026-10-19", 2, 1)], [("google.com", 5)]), calls),
                    tmp_path, NOW)
    later = NOW + timedelta(days=20)
    out = collect_traffic(api_for(traffic_handler([("2026-10-19", 7, 3), ("2026-11-08", 1, 1)], [("news.ycombinator.com", 40)]),
                                  calls), tmp_path, later)
    data = json.loads((tmp_path / "traffic.json").read_text())
    assert data["views"] == {"2026-10-05": [10, 4], "2026-10-19": [7, 3], "2026-11-08": [1, 1]} and out["days"] == 3
    assert data["referrers"]["2026-10-19"] == [["google.com", 5, 1]] and data["referrers"]["2026-11-08"][0][0] == "news.ycombinator.com"
    assert "title" not in json.dumps(data)  # page titles are not kept
    assert calls[0][1] == {"per": "day"}
