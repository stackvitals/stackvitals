"""SonarQube or SonarCloud code quality (DevLake's SonarQube plugin): the gate and measures, kept each day."""
from datetime import datetime, timezone

import httpx

from stackvitals.connectors import sonar
from stackvitals.connectors.store import ConnectorStore
from stackvitals.core.config import parse

CFG = parse('[connectors.sonar]\nproject = "acme_web"\n')[0]


def handle(req):
    if req.url.path.endswith("/measures/component"):
        assert req.url.params["component"] == "acme_web" and "Authorization" not in req.headers
        return httpx.Response(200, json={"component": {"measures": [{"metric": "bugs", "value": "3"}, {"metric": "coverage", "value": "81.5"},
                                                                     {"metric": "alert_status", "value": "ERROR"}]}})
    return httpx.Response(200, json={"projectStatus": {"status": "ERROR", "conditions": [
        {"status": "ERROR", "metricKey": "new_coverage"}, {"status": "OK", "metricKey": "new_bugs"}]}})


def test_gate_and_measures_are_kept_by_day_and_summarised(tmp_path):
    assert sonar.configured({}, CFG) and not sonar.configured({}, parse("")[0])
    for month, day in ((9, 25), (10, 28)):
        sonar.pull(ConnectorStore(tmp_path, "sonar"), {}, CFG, datetime(2026, month, day, tzinfo=timezone.utc),
                   client=httpx.Client(transport=httpx.MockTransport(handle)))
    got = sonar.summary(tmp_path, datetime(2026, 10, 29, tzinfo=timezone.utc))
    assert got["gate"] == "ERROR" and got["failing"] == ["new_coverage"] and got["measures"]["bugs"] == 3.0
    assert got["month_ago"]["coverage"] == 81.5 and len(got["days"]) == 2


def test_a_bad_project_key_is_said_plainly(tmp_path):
    import pytest
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(404, json={})))
    with pytest.raises(sonar.ConnectorError, match="no project"):
        sonar.pull(ConnectorStore(tmp_path, "sonar"), {}, CFG, datetime(2026, 10, 1, tzinfo=timezone.utc), client=client)
