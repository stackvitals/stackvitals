"""A pull request's new packages checked against the repo's licence policy, looked up on deps.dev."""
import httpx

from stackvitals.deps.supply import pr_licences


def test_new_packages_with_a_denied_licence_are_named():
    def handle(req):
        name = req.url.path.split("/packages/")[1].split("/")[0]
        lic = {"gpl-thing": ["GPL-3.0-only"], "dual": ["MIT OR GPL-3.0-only"], "ok": ["MIT"]}.get(name, [])
        return httpx.Response(200, json={"licenses": lic})
    client = httpx.Client(transport=httpx.MockTransport(handle))
    new = [("npm", "gpl-thing", "1.0.0"), ("npm", "dual", "2.0.0"), ("PyPI", "ok", "1.0"), ("Hex", "elixir", "1.0")]
    got = pr_licences(new, ["GPL-*"], client)
    assert [(x["package"], x["licence"]) for x in got] == [("gpl-thing", "GPL-3.0-only")]
