"""llms.txt at the repo root (llmstxt.org): the docs as a short index an AI agent reads first, each page with its title
and its first sentence, made from docs/ so it can't fall behind them (a test checks it is current)."""
import re
from pathlib import Path

# Shown under Optional: true but rarely what an agent needs first.
OPTIONAL = {"release-checklist.md", "threat-model.md", "roadmap.md", "chaoss.md", "enterprise.md"}
SUMMARY = ("A free, GitHub-native engineering health suite: one GitHub Action keeps CI, pull request, delivery (DORA), "
           "community and dependency history on a data branch in your own repo, with a static app, a CLI and an MCP "
           "server over it. No server of ours, no Docker.")


def _first_sentence(text: str) -> str:
    """The first plain sentence after the title: links and code kept as words, at most 220 characters."""
    body = []
    for line in text.splitlines()[1:]:
        if not line.strip():
            if body:
                break
            continue
        if line.startswith(("#", "|", "```", "-", ">", "<")):
            if body:
                break
            continue
        body.append(line.strip())
    para = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", " ".join(body)).replace("**", "").replace("`", "")
    first = re.split(r"(?<=[.!?])\s", para, maxsplit=1)[0]
    return first if len(first) <= 220 else first[:217].rsplit(" ", 1)[0] + "..."


def markdown(root: Path) -> str:
    docs = Path(root) / "docs"
    pages = sorted(p for p in docs.rglob("*.md"))
    main, optional = [], []
    for p in pages:
        text = p.read_text(encoding="utf-8")
        title = text.splitlines()[0].lstrip("# ").strip() if text.strip() else p.stem
        line = f"- [{title}]({p.relative_to(root).as_posix()}): {_first_sentence(text)}"
        (optional if p.name in OPTIONAL else main).append(line)
    return "\n".join(["# StackVitals", "", f"> {SUMMARY}", "", "## Docs", "", *main, "", "## Optional", "", *optional, ""])
