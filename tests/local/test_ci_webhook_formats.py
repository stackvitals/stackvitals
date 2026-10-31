"""The "newly flaky" webhook speaks every chat's format (the Teams card included) through the same sender as delivery
alerts, and a refused delivery is reported instead of passing silently."""
import json

import httpx

from stackvitals.ci.automation import alert_message, send_alert


def capture(status=200):
    sent = []

    def handle(request):
        sent.append((str(request.url), json.loads(request.content)))
        return httpx.Response(status)
    return sent, httpx.Client(transport=httpx.MockTransport(handle))


def test_each_chat_gets_its_own_shape():
    names = ["test t::a"]
    for url, check in (("https://hooks.slack.com/services/x", lambda b: b["text"].startswith("Newly flaky in o/r")),
                       ("https://discord.com/api/webhooks/1/x", lambda b: "embeds" in b),
                       ("https://prod.westus.logic.azure.com/workflows/x", lambda b: b["attachments"][0]["content"]["type"] == "AdaptiveCard"),
                       ("https://example.com/hook", lambda b: b["alerts"] == [{"kind": "newly_flaky", "name": "test t::a"}])):
        sent, client = capture()
        assert send_alert(url, alert_message(names, "o/r"), client=client) is None
        assert check(sent[0][1]), url


def test_a_refused_delivery_is_reported():
    _sent, client = capture(status=500)
    assert "500" in send_alert("https://hooks.slack.com/services/x", alert_message(["test t::a"], "o/r"), client=client)
