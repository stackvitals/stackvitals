from mergescout.github.identities import identities_from_env, slots


def test_missing_or_repeated_tokens_are_skipped(monkeypatch):
    monkeypatch.delenv("MS_APP_TOKEN", raising=False)
    monkeypatch.setenv("MS_ACTIONS_TOKEN", "pat")
    assert [i.name for i in identities_from_env("pat", None, client=lambda t, **kw: t)] == ["personal"]


def test_slots_follow_the_budget_share():
    assert (slots(12, 1.0), slots(12, 0.2), slots(2, 0.2)) == (12, 2, 1)
