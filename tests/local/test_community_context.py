from stackvitals.community.context import context_record, stated_response


def test_a_stated_response_time_is_read_from_contributing_text():
    assert stated_response("We aim to respond to new issues within 3 business days.") == {"hours": 72, "said": "within 3 business days"}
    assert stated_response("Maintainers will triage issues within 48 hours") == {"hours": 48, "said": "within 48 hours"}
    assert stated_response("A maintainer will review your PR in 2 weeks or so.")["hours"] == 336
    assert stated_response("Please be patient, we are volunteers.") is None
    assert stated_response("Run the tests within 5 minutes") is None


def test_the_context_record_says_what_the_repo_states_and_never_keeps_file_text():
    repo = {"isSecurityPolicyEnabled": True, "hasDiscussionsEnabled": False, "codeOfConduct": {"name": "Contributor Covenant"},
            "fundingLinks": [{"platform": "GITHUB", "url": "https://github.com/sponsors/x"}, {"platform": "OPEN_COLLECTIVE", "url": "u"}],
            "gov1": None, "gov2": {"byteSize": 900}, "gov3": None,
            "c1": {"text": "Thanks!\nWe respond to issues within 2 days."}, "c2": None, "c3": None,
            "m1": {"text": "Ann <ann@x>\nBo <bo@x>\n\n# comment\n"}, "m2": None,
            "o1": {"text": "* @acme/core\n/docs @ann @bo\n"}, "o2": None}
    got = context_record(repo)
    assert got["governance"] is True and got["security_policy"] is True and got["code_of_conduct"] == "Contributor Covenant"
    assert got["funding"] == ["GITHUB", "OPEN_COLLECTIVE"] and got["discussions"] is False
    assert got["response_policy"] == {"hours": 48, "said": "within 2 days"} and got["maintainers_listed"] == 2
    assert got["code_owners"] == 3 and "Thanks" not in str(got)
