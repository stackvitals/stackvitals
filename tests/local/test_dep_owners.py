from datetime import datetime, timedelta, timezone

from mergescout.signals.owners_watch import refresh_owners

DAY1 = datetime(2026, 10, 17, 6, tzinfo=timezone.utc)
DAY2 = DAY1 + timedelta(days=1)


def npm_latest(version, publisher="GitHub Actions", trusted=True, maintainers=("jasonsaayman",)):
    user = {"name": publisher, "email": "secret@example.com"}
    if trusted:
        user["trustedPublisher"] = {"id": "github"}
    return {"version": version, "_npmUser": user, "maintainers": [{"name": m, "email": "x@y"} for m in maintainers],
            "dist": {"attestations": {"url": "x"}} if trusted else {}}


def pypi_version(roles, org=None):
    return {"info": {"version": "2.32.3"}, "ownership": {"organization": org, "roles": [{"role": r, "user": u} for u, r in roles]}}


def test_the_first_look_is_a_baseline_and_changes_become_dated_events():
    answers = {"https://registry.npmjs.org/axios/latest": npm_latest("1.7.0"),
               "https://pypi.org/pypi/requests/2.32.3/json": pypi_version([("Lukasa", "Owner"), ("nateprewitt", "Owner")])}
    pkgs = [("npm", "axios", "1.7.0"), ("pypi", "requests", "2.32.3")]
    first = refresh_owners(pkgs, {}, DAY1, answers.get)
    ax = first["packages"]["npm:axios"]
    assert ax["events"] == [] and ax["current"]["trusted"] is True and ax["current"]["maintainers"] == ["jasonsaayman"]
    assert "secret@example.com" not in str(first)  # emails are never kept
    # Next day: axios published from a personal account without trusted publishing, and a new maintainer appears.
    answers["https://registry.npmjs.org/axios/latest"] = npm_latest("1.7.1", publisher="newperson", trusted=False,
                                                                    maintainers=("jasonsaayman", "newperson"))
    answers["https://pypi.org/pypi/requests/2.32.3/json"] = pypi_version([("Lukasa", "Owner"), ("nateprewitt", "Owner")], org="psf")
    second = refresh_owners(pkgs, first, DAY2, answers.get)
    kinds = {e["kind"]: e for e in second["packages"]["npm:axios"]["events"]}
    assert kinds["trusted_lost"]["date"] == "2026-10-18" and kinds["maintainer_added"]["who"] == ["newperson"]
    assert kinds["publisher_changed"]["to"] == "newperson"
    assert [e["kind"] for e in second["packages"]["pypi:requests"]["events"]] == ["organization_changed"]
    assert second["packages"]["npm:axios"]["since"] == "2026-10-17"


def test_a_lost_answer_keeps_yesterdays_snapshot_and_no_event():
    pkgs = [("npm", "axios", "1.7.0")]
    first = refresh_owners(pkgs, {}, DAY1, {"https://registry.npmjs.org/axios/latest": npm_latest("1.7.0")}.get)

    def broken(url):
        raise OSError("reset")
    second = refresh_owners(pkgs, first, DAY2, broken)
    assert second["packages"]["npm:axios"] == first["packages"]["npm:axios"]


def test_the_daily_snapshot_watches_the_mapped_packages(tmp_path, monkeypatch):
    import json

    import mergescout.signals.owners_watch as ow
    from mergescout.snapshot.__main__ import write_owners
    (tmp_path / "deps-map.json").write_text(json.dumps({"packages": {"pypi:requests": {"version": "2.32.3"},
                                                                     "npm:axios": {"version": "1.7.0"}}}), encoding="utf-8")
    seen = {}

    def fake(packages, previous, now, **kw):
        seen.update(packages=packages)
        return {"built_at": "t", "packages": {"npm:axios": {"current": {}, "since": "2026-10-18", "events": []}}}
    monkeypatch.setattr(ow, "refresh_owners", fake)
    said = []
    write_owners(tmp_path, DAY2, said.append)
    assert seen["packages"] == [("npm", "axios", "1.7.0"), ("pypi", "requests", "2.32.3")]
    assert json.loads((tmp_path / "deps-owners.json").read_text(encoding="utf-8"))["packages"]["npm:axios"]["since"] == "2026-10-18"
    assert any("ownership watch" in s for s in said)
