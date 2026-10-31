"""Chat messages in each chat's own shape: Slack Block Kit with link buttons (and Slack's own markdown), a Teams Adaptive
Card with open-link actions (Teams Workflows), a Discord embed, or plain JSON for anything else; and which webhook a
team's message goes to. Buttons only open links: nothing here needs a server to answer clicks."""
import re

import httpx

BOLD = re.compile(r"\*\*(.+?)\*\*")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
TEAM_LINE = re.compile(r"^\s*(@?[\w.-]+(?:/[\w.-]+)?)\s*=\s*(https://\S+)\s*$")
SLACK_SECTION, SLACK_BLOCKS, SLACK_BUTTONS, DISCORD_TEXT = 3000, 50, 5, 4096


def message(title: str, lines: list[str], links=(), data: dict | None = None) -> dict:
    """What every chat gets: a title, Markdown lines (**bold**, `code`, [text](url)), up to five link buttons, and the
    numbers for plain JSON webhooks."""
    return {"title": title, "lines": list(lines), "links": list(links), "data": data or {}}


def safe(name, size: int = 200) -> str:
    """A name from the repo (a test, a job, a package) as inert text: one line that can't become a link (no chat pings plain @names)."""
    out = " ".join(str(name).split())[:size].replace("`", "'")
    return out.replace("](", "]\u200b(").replace("://", ":\u200b//")


def kind(url: str) -> str:
    if "hooks.slack.com" in url:
        return "slack"
    if "discord.com/api/webhooks" in url or "discordapp.com/api/webhooks" in url:
        return "discord"
    if "logic.azure.com" in url or "webhook.office.com" in url or "powerplatform.com" in url:
        return "teams"
    return "json"


def text(msg: dict) -> str:
    """The message as plain lines (job summaries, fallbacks)."""
    return "\n".join([msg["title"], *msg["lines"]])


def _slack_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _slack_md(text: str) -> str:
    text = _slack_escape(text)
    return LINK.sub(r"<\2|\1>", BOLD.sub(r"*\1*", text))


def _chunks(lines: list[str], size: int) -> list[str]:
    out, cur = [], ""
    for line in lines:
        line = line[:size]
        if cur and len(cur) + 1 + len(line) > size:
            out.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    return out + ([cur] if cur else [])


def _slack(msg: dict) -> dict:
    blocks = [{"type": "header", "text": {"type": "plain_text", "text": msg["title"][:150]}}]
    sections = _chunks([_slack_md(x) for x in msg["lines"]], SLACK_SECTION)
    room = SLACK_BLOCKS - 1 - (1 if msg["links"] else 0)
    blocks += [{"type": "section", "text": {"type": "mrkdwn", "text": s}} for s in sections[:room]]
    if msg["links"]:
        blocks.append({"type": "actions", "elements": [
            {"type": "button", "text": {"type": "plain_text", "text": label[:75]}, "url": url}
            for label, url in msg["links"][:SLACK_BUTTONS]]})
    # The fallback is read as Slack markup too (notifications), so it is escaped like the sections.
    return {"text": _slack_escape(text(msg))[:3000], "blocks": blocks}


def _teams(msg: dict) -> dict:
    card = {"type": "AdaptiveCard", "version": "1.4", "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "body": [{"type": "TextBlock", "text": msg["title"], "weight": "Bolder", "size": "Medium", "wrap": True},
                     *({"type": "TextBlock", "text": line, "wrap": True} for line in msg["lines"])],
            "actions": [{"type": "Action.OpenUrl", "title": label, "url": url} for label, url in msg["links"][:SLACK_BUTTONS]]}
    return {"type": "message", "attachments": [{"contentType": "application/vnd.microsoft.card.adaptive", "content": card}]}


def _discord(msg: dict) -> dict:
    links = " · ".join(f"[{label}]({url})" for label, url in msg["links"])
    body = "\n".join(msg["lines"])
    room = DISCORD_TEXT - len(links) - 2
    text = (body if len(body) <= room else body[:room - 1] + "…") + (f"\n\n{links}" if links else "")
    return {"embeds": [{"title": msg["title"][:256], "description": text[:DISCORD_TEXT],
                        **({"url": msg["links"][0][1]} if msg["links"] else {})}], "allowed_mentions": {"parse": []}}


def payload(url: str, msg: dict) -> dict:
    shape = kind(url)
    if shape == "slack":
        return _slack(msg)
    if shape == "teams":
        return _teams(msg)
    if shape == "discord":
        return _discord(msg)
    return {"source": "stackvitals", "title": msg["title"], "text": text(msg),
            "links": [{"label": label, "url": url} for label, url in msg["links"]], **msg["data"]}


def post(url: str, msg: dict, client: httpx.Client | None = None, what: str = "the webhook") -> str | None:
    """Post a message in the chat's own shape; a failure comes back as text for the job summary, never as an exception."""
    url = url.strip()  # a secret pasted with a trailing newline
    try:
        response = (client or httpx.Client(timeout=30)).post(url, json=payload(url, msg))
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        return f"Could not send {what} ({type(exc).__name__})."
    if response.status_code >= 300:
        return f"{what[0].upper()}{what[1:]} answered {response.status_code}."
    return None


def app_url(repo: str, info: dict | None, route: str = "") -> str | None:
    """The monitor's address on GitHub Pages, when the repo is public and publishes Pages; else None."""
    if not info or info.get("private") or not info.get("has_pages"):
        return None
    owner, name = repo.split("/")
    base = f"https://{owner.lower()}.github.io/" if name.lower() == f"{owner.lower()}.github.io" else f"https://{owner.lower()}.github.io/{name}/"
    return base + (f"#/{route}" if route else "")


def team_hooks(env: dict) -> dict[str, str]:
    """`STACKVITALS_TEAM_WEBHOOKS`, one `owner = https://...` per line (owners as CODEOWNERS names them, @org/team)."""
    out = {}
    for line in (env.get("STACKVITALS_TEAM_WEBHOOKS") or "").splitlines():
        found = TEAM_LINE.match(line)
        if found:
            out[found.group(1)] = found.group(2)
    return out


def route(owners_by_item: dict[str, list[str]], env: dict) -> dict[str, list[str]]:
    """Which webhook gets which items: each owning team with its own webhook gets its items, the rest go to the default."""
    teams, default = team_hooks(env), (env.get("STACKVITALS_WEBHOOK") or "").strip()
    out = {}
    for item, owners in owners_by_item.items():
        hooks = [teams[o] for o in owners or [] if o in teams]
        for hook in dict.fromkeys(hooks or ([default] if default else [])):
            out.setdefault(hook, []).append(item)
    return out
