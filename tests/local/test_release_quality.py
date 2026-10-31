"""Quality per release: what each release shipped, how much of it was fixes, and what followed it (reverts of its
own pull requests, incidents in the next two weeks)."""
from datetime import datetime, timezone

from stackvitals.core import releases

NOW = datetime(2026, 10, 29, tzinfo=timezone.utc)


def test_each_release_gets_its_prs_fixes_reverts_and_later_incidents():
    rel = [{"tag": "v1.0.0", "at": "2026-09-01T00:00:00Z"}, {"tag": "v1.1.0", "at": "2026-10-01T00:00:00Z"},
           {"tag": "v1.2.0-rc1", "at": "2026-10-10T00:00:00Z", "pre": True}, {"tag": "v1.2.0", "at": "2026-10-20T00:00:00Z"}]
    prs = [{"n": 1, "ti": "fix: crash on empty input", "mg": "2026-09-10T00:00:00Z"},
           {"n": 2, "ti": "feat: add export", "mg": "2026-09-20T00:00:00Z"},
           {"n": 3, "ti": "feat: new parser", "mg": "2026-10-05T00:00:00Z"},
           {"n": 4, "ti": 'Revert "feat: add export" (#2)', "mg": "2026-10-03T00:00:00Z"}]
    incidents = [{"created": "2026-10-05T00:00:00Z"}, {"created": "2026-11-30T00:00:00Z"}]
    got = releases.quality(prs, rel, incidents, NOW)
    assert [r["tag"] for r in got] == ["v1.2.0", "v1.1.0"]
    newest, older = got
    assert (older["prs"], older["fixes"], older["fix_share"], older["reverted"], older["incidents_after"], older["settled"]) == \
        (2, 1, 0.5, [2], 1, True)
    assert (newest["prs"], newest["reverted"], newest["settled"]) == (1, [], False)


def test_one_release_is_not_enough():
    assert releases.quality([], [{"tag": "v1", "at": "2026-10-01T00:00:00Z"}], [], NOW) is None
