"""Chat messages in each chat's own shape: Slack Block Kit with link buttons and Slack's own markdown, a Teams Adaptive
Card with open-link actions, a Discord embed, plain JSON elsewhere; within each one's limits; one webhook per team."""
from stackvitals.core import chat

LINKS = [("Open Delivery", "https://o.github.io/r/#/delivery"), ("Alerts issue", "https://github.com/o/r/issues/3")]
MSG = chat.message("StackVitals alerts for o/r", ["- **Pickup P75** over its limit: 30.0 against 4.0 (n=20).",
                                                  "See [the PR](https://github.com/o/r/pull/1)."],
                   links=LINKS, data={"alerts": [{"metric": "pickup_p75_hours"}]})


def test_slack_gets_block_kit_with_its_own_markdown_and_link_buttons():
    p = chat.payload("https://hooks.slack.com/services/x", MSG)
    assert p["text"].startswith("StackVitals alerts for o/r")
    assert p["blocks"][0] == {"type": "header", "text": {"type": "plain_text", "text": "StackVitals alerts for o/r"}}
    body = p["blocks"][1]["text"]["text"]
    assert "*Pickup P75*" in body and "**" not in body and "<https://github.com/o/r/pull/1|the PR>" in body
    buttons = p["blocks"][-1]["elements"]
    assert [(b["text"]["text"], b["url"]) for b in buttons] == LINKS and all(b["type"] == "button" for b in buttons)


def test_teams_gets_an_adaptive_card_with_open_link_actions():
    p = chat.payload("https://prod-01.westus.logic.azure.com/workflows/x", MSG)
    card = p["attachments"][0]["content"]
    assert card["type"] == "AdaptiveCard" and card["body"][0]["text"] == "StackVitals alerts for o/r"
    assert [(a["type"], a["title"], a["url"]) for a in card["actions"]] == [("Action.OpenUrl", *x) for x in LINKS]


def test_discord_gets_an_embed_with_the_links():
    p = chat.payload("https://discord.com/api/webhooks/1/x", MSG)
    embed = p["embeds"][0]
    assert embed["title"] == "StackVitals alerts for o/r" and "[Open Delivery](https://o.github.io/r/#/delivery)" in embed["description"]


def test_other_webhooks_get_plain_json_with_the_data_and_links():
    p = chat.payload("https://example.com/hook", MSG)
    assert p["source"] == "stackvitals" and p["alerts"] == [{"metric": "pickup_p75_hours"}]
    assert p["links"][0] == {"label": "Open Delivery", "url": "https://o.github.io/r/#/delivery"} and "Pickup P75" in p["text"]


def test_long_messages_fit_each_chats_limits():
    big = chat.message("T" * 300, [f"- line {k} " + "x" * 120 for k in range(300)], links=[(f"L{k}", f"https://x/{k}") for k in range(9)])
    slack = chat.payload("https://hooks.slack.com/services/x", big)
    assert len(slack["blocks"]) <= 50 and all(len(b["text"]["text"]) <= 3000 for b in slack["blocks"] if b["type"] == "section")
    assert len(slack["blocks"][0]["text"]["text"]) <= 150 and len(slack["blocks"][-1]["elements"]) <= 5
    embed = chat.payload("https://discord.com/api/webhooks/1/x", big)["embeds"][0]
    assert len(embed["description"]) <= 4096 and len(embed["title"]) <= 256


def test_a_team_webhook_gets_its_owners_messages_and_the_rest_go_to_the_default():
    env = {"STACKVITALS_WEBHOOK": "https://hooks.slack.com/default",
           "STACKVITALS_TEAM_WEBHOOKS": "@acme/web = https://hooks.slack.com/web\n@acme/api=https://hooks.slack.com/api\nbad line\n"
                                        "@acme/x = http://plain.example.com"}
    assert chat.team_hooks(env) == {"@acme/web": "https://hooks.slack.com/web", "@acme/api": "https://hooks.slack.com/api"}
    groups = chat.route({"test a": ["@acme/web", "@bob"], "test b": ["@bob"], "test c": ["@acme/api", "@acme/web"]}, env)
    assert groups == {"https://hooks.slack.com/web": ["test a", "test c"], "https://hooks.slack.com/api": ["test c"],
                      "https://hooks.slack.com/default": ["test b"]}
    assert chat.route({"test a": []}, {}) == {}
