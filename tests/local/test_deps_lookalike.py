from stackvitals.deps.lookalike import lookalike

POPULAR = {"npm": {"lodash", "express", "react-dom", "axios", "chai"}, "pypi": {"requests", "python-dateutil", "urllib3"}}


def test_one_edit_from_a_popular_name_is_a_lookalike():
    assert lookalike("npm", "lodahs", POPULAR) == "lodash"     # swapped letters
    assert lookalike("npm", "expresss", POPULAR) == "express"  # one added
    assert lookalike("pypi", "reqests", POPULAR) == "requests"  # one dropped
    assert lookalike("pypi", "urlib3", POPULAR) == "urllib3"
    assert lookalike("npm", "reactdom", POPULAR) == "react-dom"  # separators only
    assert lookalike("pypi", "python_dateutil", POPULAR) is None  # the same name as PyPI normalises it


def test_popular_names_short_names_scoped_names_and_unrelated_ones_are_not():
    assert lookalike("npm", "lodash", POPULAR) is None
    assert lookalike("npm", "chain", POPULAR) is None   # under five letters in the popular name: too many real neighbours
    assert lookalike("npm", "@types/lodash", POPULAR) is None
    assert lookalike("npm", "lodash-es", POPULAR) is None
    assert lookalike("npm", "something-else", POPULAR) is None
    assert lookalike("npm", "lodahs", {}) is None


def _client(counts):
    import httpx

    def handler(request):
        name = request.url.path.rsplit("/", 1)[-1] if "npmjs" in request.url.host else request.url.path.split("/")[-2]
        if name not in counts:
            return httpx.Response(404, json={})
        body = {"downloads": counts[name]} if "npmjs" in request.url.host else {"data": {"last_week": counts[name]}}
        return httpx.Response(200, json=body)
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_weekly_downloads_come_from_each_registry_and_a_miss_is_none():
    from stackvitals.deps.lookalike import weekly_downloads
    client = _client({"lodahs": 3, "reqests": 12})
    assert weekly_downloads("npm", "lodahs", client) == 3
    assert weekly_downloads("pypi", "reqests", client) == 12
    assert weekly_downloads("npm", "missing", client) is None


def test_an_added_lookalike_with_few_downloads_is_flagged_and_a_well_used_one_is_not():
    from stackvitals.deps.lookalike import judge
    popular = {"npm": {"lodash", "safe-buffer"}}
    flagged = judge("npm", "lodahs", popular, _client({"lodahs": 3}))
    assert flagged["verdict"] == "investigate" and "lodash" in flagged["reasons"][0] and "3 downloads" in flagged["reasons"][0]
    assert judge("npm", "safer-buffer", popular, _client({"safer-buffer": 192455187})) is None
    assert judge("npm", "unrelated", popular, _client({})) is None
