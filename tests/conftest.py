import gzip
import os

import orjson
import pytest

# Tests create many throwaway git repos; a system-wide core.fsmonitor would leave a watcher process for each.
os.environ.update({"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "core.fsmonitor", "GIT_CONFIG_VALUE_0": "false"})


def pytest_collection_modifyitems(config, items):
    # Network tests only run when asked, so the normal suite stays offline.
    if os.environ.get("MS_NETWORK_TESTS") == "1":
        return
    skip = pytest.mark.skip(reason="network test; set MS_NETWORK_TESTS=1 to run")
    for item in items:
        if "network" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    # Tests never reach the network: a real request gets the 401 GitHub gives a made-up token, at once and without leaving
    # the machine (mock transports still answer; servers a test starts on this machine still work).
    if os.environ.get("MS_NETWORK_TESTS") == "1":
        return
    import httpx
    real = httpx.HTTPTransport.handle_request

    def offline(self, request):
        if request.url.host in ("127.0.0.1", "localhost", "::1"):
            return real(self, request)
        return httpx.Response(401, json={"message": "Bad credentials (tests run offline)"}, request=request)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", offline)


@pytest.fixture(autouse=True)
def _no_top_list_download(monkeypatch):
    # The daily map asks ecosyste.ms for the most-used packages; tests never go to the network (the crawler copy has no map).
    try:
        import mergescout.signals.top_packages as tp
    except ImportError:
        return
    monkeypatch.setattr(tp, "http_get_json", lambda url, **k: [])


@pytest.fixture
def make_gz():
    def _make(events, extra_lines=()):
        lines = [orjson.dumps(e) for e in events] + [line.encode() for line in extra_lines]
        return gzip.compress(b"\n".join(lines) + b"\n")
    return _make


class FakeGQL:
    def __init__(self, responder):
        self.responder = responder
        self.calls = []
        self.kwargs = []

    def query(self, query, variables=None, **kw):
        from mergescout.github.graphql import GraphQLResult
        variables = variables or {}
        self.calls.append((query, variables))
        self.kwargs.append(kw)
        data, cost = self.responder(query, variables)
        return GraphQLResult(data=data, cost=cost, remaining=4000, reset_at="2026-10-11T00:00:00Z")


@pytest.fixture
def fake_gql():
    return FakeGQL
