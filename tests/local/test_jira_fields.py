"""Tracker custom fields mapped in settings (DevLake's customize plugin): a Jira field for the team and one for an
incident's severity, by name or id, kept on each issue and counted."""
from stackvitals.connectors import jira, tracker
from stackvitals.core.config import parse

FIELDS = [{"id": "customfield_10001", "name": "Team", "schema": {"custom": "com.atlassian.teams"}},
          {"id": "customfield_10020", "name": "Severity", "schema": {"custom": "select"}}]


def raw(key, team, sev):
    return {"id": key, "key": key, "fields": {"summary": "x", "issuetype": {"name": "Bug"}, "status": {"name": "Done", "statusCategory": {"key": "done"}},
                                             "created": "2026-10-01T00:00:00.000+0000", "updated": "2026-10-02T00:00:00.000+0000",
                                             "customfield_10001": {"id": "t1", "name": team}, "customfield_10020": {"value": sev}},
            "changelog": {"histories": []}}


def test_fields_are_found_by_name_or_id_and_kept_as_text():
    assert jira.field_id(FIELDS, "team") == "customfield_10001" and jira.field_id(FIELDS, "customfield_10020") == "customfield_10020"
    assert jira.field_id(FIELDS, "nope") is None
    recs = jira._records(raw("WEB-1", "Payments", "Sev 1"), "https://a.atlassian.net", None, None, True,
                         {"team": "customfield_10001", "severity": "customfield_10020"})
    issue = recs[0]
    assert issue["team"] == "Payments" and issue["severity"] == "Sev 1"
    assert tracker.incidents([{**issue, "incident": True}])[0]["severity"] == "Sev 1"


def test_the_settings_take_a_field_name_and_refuse_a_long_one():
    cfg, notes = parse('[connectors.jira]\nteam_field = "Team"\nseverity_field = "' + "x" * 101 + '"\n')
    assert cfg["connectors"]["jira"]["team_field"] == "Team" and cfg["connectors"]["jira"]["severity_field"] == "" and notes
