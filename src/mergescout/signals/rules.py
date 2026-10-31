from dataclasses import dataclass


@dataclass(frozen=True)
class Rules:
    window_days: int = 365
    min_decided: int = 20
    min_closed: int = 10
    min_reviewed: int = 5
    claim_days: int = 14
    interest_days: int = 30
    stale_days: int = 180
    pr_cap: int = 300


RULES = Rules()

# Accounts that act like bots but are typed as users; extend when the hand-check finds more.
KNOWN_BOTS = frozenset({
    "miss-islington", "bors", "homu", "k8s-ci-robot", "k8s-triage-robot", "k8s-merge-robot", "pytorchbot",
    "facebook-github-bot", "googlebot", "google-cla", "copybara-service", "tensorflow-jenkins", "rustbot",
    "rust-highfive", "rust-timer", "nodejs-github-bot", "chromium-wpt-export-bot", "mergify", "kodiakhq",
    "allcontributors", "stale", "netlify", "vercel", "coveralls", "codecov-commenter", "sonarcloud",
    "openshift-ci-robot", "openshift-merge-robot", "ti-chi-bot", "ti-srebot", "elasticmachine", "apache-bot",
    "copilot-pull-request-reviewer", "coderabbitai", "gemini-code-assist", "sourcery-ai", "greptile-apps",
    "home-assistant", "welcome", "linear", "similar-issues-ai", "oss-sentinel-ai", "hfla-graphql-app",
    # CI accounts that open failing-test issues (seen 2026-10-16).
    "kibanamachine", "elasticsearchmachine", "brave-builds", "gordontheturtle",
})
# Comments carry no account type, so bots that only comment are known by their names (seen on 2,545 repos).
BOT_NAME_PATTERN = r"(bot|-ci|github-actions|-automation|-integration)$"
UNKNOWN_LOGINS = frozenset({"ghost"})
# Accounts that are AI coding agents, not ordinary automation; their PRs count as AI-written.
AI_AGENT_LOGINS = frozenset({"copilot-swe-agent", "devin-ai-integration", "chatgpt-codex-connector", "cursor-agent",
                             "sweep-ai", "openhands-agent", "openhands-ai"})
# Plain words a person can also use as a login: AI only when the account is a bot.
AI_AGENT_BOT_NAMES = frozenset({"copilot", "claude", "codex", "cursor", "devin"})

# Real comments also say "...speaker and would like to work on this" and "I'll open a PR" (symfony#66111).
CLAIM_PATTERN = (r"(i('d| would) (like|love) to (work on|take|tackle|pick)"
                 r"|\band would (like|love) to (work on|take|tackle|pick up) (this|it)\b"
                 r"|(can|could|may) i (work on|take|pick|tackle|try)"
                 r"|assign (this|it) to me|please assign|^/assign|i('m| am) (working|taking) (on )?(this|it)"
                 r"|let me (take|work on|try|pick)|i('ll| will) (take|work on|pick up|try) (this|it)"
                 r"|i('ll| will) (open|submit|send|raise|create) (a )?(pr|pull request)\b)")
WAIT_PATTERN = (r"(please (wait|hold)|on hold|blocked (by|on)|needs? (design|discussion|decision|triage)"
                r"|not (ready|accepting)|we('re| are) (still )?(discussing|deciding)|do not (open|send) (a )?(pr|pull))")
# Surnames that end in "bot" (seen: adamrtalbot); RE2 has no lookbehind, so they are excluded separately.
HUMAN_BOT_NAMES = r"(talbot|abbot|cabot|sabot)$"
# Labels (after norm_label) that say the issue is not ready for a PR, e.g. "status: blocked", "needs info".
# Anchored: real labels "triage accepted", "never stale", "question bank" and "triage needs pr" mean ready or a topic.
PREFIX = r"^((status|state|type|kind|resolution|issue|s|t) )?"
WAITING = r"(design|discussion|decision|info|information|feedback|repro|reproduction|investigation|confirmation)"
# Also labels saying someone is on it ("in progress", "claimed", "gssoc assigned") or it is done ("fixed").
WAIT_LABEL_PATTERN = (rf"{PREFIX}(blocked|on hold|wontfix|won t fix|invalid|duplicate|not planned|"
                      rf"maybe later|(\d+ )?in progress|work in progress|wip|claimed( \w+)?|"
                      rf"taken|has pr|pr open|pr submitted|fixed|resolved( pending close)?|(wait|waiting) for review)$"
                      rf"|\bneeds? (more )?{WAITING}\b|\b(awaiting|waiting for|waiting on|pending|requires) "
                      rf"({WAITING}|response|reply)\b|\btriage needs {WAITING}\b"
                      r"|^(gssoc|gsoc|ssoc|hacktoberfest|kwoc|swoc|jwoc|iwoc|dwoc|osci)\w* assigned$")
# "Not settled yet" labels (triage, question, proposal). Repos add them to every new issue or keep them after a
# decision (golang: "Proposal" + "Proposal-Accepted"), so a beginner or help label added later outweighs them.
TRIAGE_LABEL_PATTERN = (rf"{PREFIX}(triage|untriaged|unconfirmed|question|discussion|in discussion|rfc|proposal)$"
                        r"|\bneeds? triage\b|\b(awaiting|waiting for|pending|requires) triage\b"
                        r"|\btriage (needed|pending|required)\b")
# Titles like "[RFC] ..." or "Epic: ..." and labels like "epic" mark trackers and debates, not tasks.
KINDS = r"(epic|rfc|discussion|tracking|tracker|meta|roadmap|proposal|umbrella|poll|survey)"
DISCUSSION_TITLE = rf"^\s*[\[(]\s*{KINDS}\s*[\])]|^\s*{KINDS}\s*:|\btracking issue\b|^\s*dependency dashboard\s*$"
LABEL_KINDS = r"(epic|tracking|tracker|roadmap|umbrella|poll|survey)"
DISCUSSION_LABEL = rf"^((type|kind) )?{LABEL_KINDS}$"
