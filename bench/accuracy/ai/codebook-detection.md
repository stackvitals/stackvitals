# Codebook: does a pull request say an AI tool made it or helped?

You see one pull request from a public repo: who opened it (login and account type), its branch, title, description,
labels and the messages of its commits (the first 100). Decide what the pull request itself states about AI
involvement. You don't see any rule's answer and shouldn't guess one.

## Fields

**involvement**: one of
- `agent`: a coding agent produced the pull request: it was opened by an agent's account (Copilot coding agent,
  devin-ai-integration, a Codex or Cursor or Claude bot account), or the description or commits say an agent wrote it
  as a task ("created by Codex", a Codex task or Devin session link, "Cursor background agent", "This PR was generated
  by Claude Code from issue #12"), or the branch is one an agent creates (codex/, copilot/, cursor/, devin/, claude/)
  and nothing says a person wrote the change.
- `assisted`: a person wrote or drove the change and the pull request says an AI tool helped: a co-author trailer
  naming an AI tool (Co-authored-by: Claude, Copilot, Cursor, Codex, Gemini, Aider), a footer such as "Generated with
  Claude Code" or "Made with Cursor", a sentence such as "I used ChatGPT to write the tests", or a label such as
  ai-assisted.
- `none`: nothing in what you see states AI involvement. Writing style, emoji, tidy bullet lists or long descriptions
  never count on their own; neither does a dependency bot, a CI bot, or a mention of AI as the subject of the change
  (a PR that adds an OpenAI client is not AI-made).
- `unclear`: something hints at AI but doesn't say it (a link to a chat with no words around it, "with some help"),
  or the statement contradicts itself.

**evidence**: at most 200 characters quoted from what decided it (the login, the branch, the trailer, the sentence).
Empty for `none`.

**confidence**: `high` when stated plainly, `medium` when it takes a small inference, `low` otherwise.

## Labelling protocol

The same as the other cards: Claude labels first; Gemini 3.5 Flash-Lite labels blind with this codebook and the same
view; a third reading settles disagreements, seeing the two answers as A and B in random order. Published: links,
strata and labels, never descriptions or commit text. No person has audited the labels.
