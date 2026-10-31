from datetime import datetime, timezone

from stackvitals.community.affiliation import key, normalize
from stackvitals.community.analyze import cohorts, elephant

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def pr(n, au, mg="2026-09-01T00:00:00Z", cr=None):
    return {"n": n, "au": au, "at": "User", "mg": mg, "cr": cr or mg, "as": "CONTRIBUTOR"}


def test_company_names_are_normalised_and_self_employment_is_not_a_company():
    assert normalize("@google") == normalize("Google LLC") == normalize("google, inc.") == "google"
    assert normalize("Microsoft Corp.") == "microsoft" and normalize("  @Red-Hat ") == "red-hat"
    assert normalize("Freelance") is None and normalize("independent") is None and normalize("") is None
    assert normalize("@acme @other") == "acme"


def test_the_elephant_factor_counts_organisations_behind_half_the_work_and_shows_unknowns():
    prs = [pr(i, "ann") for i in range(10)] + [pr(10 + i, "bo") for i in range(6)] + [pr(20 + i, "cy") for i in range(4)] \
        + [pr(30 + i, "dee") for i in range(5)]
    aff = {key("ann"): "google", key("bo"): "google", key("cy"): "red-hat"}
    got = elephant(prs, aff, NOW)
    # Known work 20 PRs: google 16 of 20, so one organisation carries half.
    assert got["factor"] == 1 and got["merged"] == 25 and got["unknown_share"] == 0.2
    assert got["orgs"][0] == {"org": "google", "prs": 16, "share": 0.64} and got["people"] == 4
    # Mostly unknown: no factor is claimed.
    assert elephant(prs, {key("cy"): "red-hat"}, NOW)["factor"] is None


def test_retention_cohorts_count_newcomers_still_contributing_months_on():
    prs = [pr(1, "ann", "2026-03-05T00:00:00Z"), pr(2, "ann", "2026-04-20T00:00:00Z"),  # back after 46 days
           pr(3, "bo", "2026-03-10T00:00:00Z"),                                       # never back
           pr(4, "cy", "2026-03-12T00:00:00Z"), pr(5, "cy", "2026-07-01T00:00:00Z"),  # back after 111 days
           pr(6, "dee", "2026-10-01T00:00:00Z"),                                      # too new to judge
           pr(7, "early", "2025-10-01T00:00:00Z")]                                    # history starts here
    got = {c["month"]: c for c in cohorts(prs, [], NOW)["months"]}
    assert got["2026-03"]["newcomers"] == 3 and got["2026-03"]["back_by_90d"] == 1 and got["2026-03"]["back_90_180d"] == 1
    assert got["2026-10"]["back_by_90d"] is None


def test_people_who_triage_others_issues_count_as_answering_for_the_project():
    from stackvitals.community.analyze import regular_responders, triagers
    issues = [{"n": 1, "au": "asker", "cr": "2026-10-01T00:00:00Z", "up": "2026-10-02T00:00:00Z", "cl": "2026-10-02T00:00:00Z",
               "tr": [["tri", "2026-10-01T05:00:00Z"]], "clb": "closer", "cm": []},
              {"n": 2, "au": "self", "cr": "2026-10-01T00:00:00Z", "up": "2026-10-02T00:00:00Z", "cl": "2026-10-02T00:00:00Z",
               "tr": [], "clb": "self", "cm": []},
              # Updated lately, but the label is two years old: an old act doesn't make someone a responder now.
              {"n": 3, "au": "old", "cr": "2024-01-01T00:00:00Z", "up": "2026-10-02T00:00:00Z", "tr": [["gone", "2024-01-02T00:00:00Z"]],
               "cm": []}]
    assert triagers(issues, NOW) == {"tri", "closer"}  # an author closing their own issue doesn't count; old acts don't
    assert regular_responders([], issues, {"maint"}, NOW) == {"tri", "closer"}


def test_an_organisation_of_one_person_is_never_named_alone():
    prs = [pr(i, "ann") for i in range(10)] + [pr(10 + i, "bo") for i in range(6)] + [pr(20 + i, "cy") for i in range(4)]
    got = elephant(prs, {key("ann"): "google", key("bo"): "google", key("cy"): "red-hat"}, NOW)
    assert [o["org"] for o in got["orgs"]] == ["google", "organisations of one person"] and "red-hat" not in str(got)


def test_a_deleted_account_answers_null_and_the_rest_are_still_found():
    from stackvitals.community.affiliation import collect

    class Result:
        def __init__(self, data):
            self.data = data

    class Gql:
        def query(self, q, v, partial=False):
            assert partial
            return Result({"u0": None, "u1": {"company": "@acme"}})
    assert collect(Gql(), ["gone", "ann"]) == {key("gone"): None, key("ann"): "acme"}


def test_cohorts_start_once_the_history_is_complete():
    # Review finding: everyone in the oldest stored months was counted as a newcomer.
    old = [pr(i, f"reg{i}", "2025-11-03T00:00:00Z") for i in range(5)] + [pr(10 + i, f"reg{i}", "2025-12-20T00:00:00Z") for i in range(5)]
    months = {c["month"] for c in cohorts(old + [pr(30, "new", "2026-06-01T00:00:00Z")], [], NOW)["months"]}
    assert "2025-11" not in months and "2026-06" in months
