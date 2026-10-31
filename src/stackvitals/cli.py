import argparse
import os
import sys

MODULES = {
    "ci": "CI health: flaky and slow jobs (`stackvitals ci report owner/repo`)",
    "flow": "Team Flow: who acts next on pull requests (`stackvitals flow report owner/repo`)",
    "deps": "Dependency Steward: should you add or upgrade a package (`stackvitals deps check requests`)",
    "portal": "Portal: what an org owns, who owns it, and its shape (`stackvitals portal report my-org`)",
    "community": "Community: where newcomers drop out and how fast they get a first answer (`stackvitals community report owner/repo`)",
    "contribute": "Contribute: open-source issues you can get merged, and how changes get merged in a repo (`stackvitals contribute brief owner/repo`)",
}


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="stackvitals", description="Free, open-source developer suite.")
    sub = parser.add_subparsers(dest="module", required=True)
    for name, text in MODULES.items():
        sub.add_parser(name, add_help=False, help=text)
    sub.add_parser("init", add_help=False, help="Set up StackVitals in one of your repos in one command (`stackvitals init owner/repo`)")
    sub.add_parser("action", add_help=False, help="Run inside GitHub Actions (used by the StackVitals Action)")
    serve = sub.add_parser("serve", help="Run the MCP server on stdio (MergeScout and CI Health tools)")
    serve.add_argument("--tools", choices=["core", "all"], help="core: the 11 core tools (default); all: every tool "
                       "(or set STACKVITALS_MCP_TOOLS=all)")
    sub.add_parser("record", add_help=False, help="Send a deployment or incident from any tool (`stackvitals record deployment owner/repo --id 42 --sha abc1234`)")
    sub.add_parser("project", add_help=False, help="DORA for one project across several repos, as DevLake counts a project (`stackvitals project web org/a org/b`)")
    sub.add_parser("delivery", add_help=False, help="Cycle time, DORA and stuck PRs (`stackvitals delivery owner/repo`)")
    sub.add_parser("ui", add_help=False, help="Open a repo's pages, Explore included, from a local copy (`stackvitals ui owner/repo`)")
    sub.add_parser("explain", add_help=False, help="What a headline number was counted from (`stackvitals explain owner/repo lead-time`)")
    sub.add_parser("export", add_help=False, help="A repo's data as DevLake tables or a CTRF test report (`stackvitals export owner/repo --format devlake|ctrf`)")
    sub.add_parser("insights", add_help=False, help="What to fix first, and how long merged PRs sat with failing checks (`stackvitals insights owner/repo`)")
    sub.add_parser("sql", add_help=False, help="SQL over a repo's summaries (`stackvitals sql --repo owner/name \"select ...\"`)")
    sub.add_parser("propose", add_help=False, help="A link proposing a settings change or decision that a person submits (`stackvitals propose owner/repo --set alerts.pickup_p75_hours=6`)")
    sub.add_parser("site", add_help=False, help="Build the project site: landing page, the app and its demo (`stackvitals site build --out DIR`)")
    sub.add_parser("connectors", add_help=False, help="Test each connector's key (`stackvitals connectors check jira slack`, or --all)")
    sub.add_parser("editor", add_help=False, help="Mark flaky tests in your editor (`stackvitals editor vscode|cursor|vscodium`)")
    # Module commands parse their own arguments.
    args, rest = parser.parse_known_args(argv)
    if args.module == "ci":
        from stackvitals.ci.cli import main as ci_main
        return ci_main(rest)
    if args.module == "flow":
        import stackvitals.flow.cli as flow_cli
        return flow_cli.main(rest)
    if args.module == "deps":
        from stackvitals.deps.cli import main as deps_main
        return deps_main(rest)
    if args.module == "portal":
        from stackvitals.portal.cli import main as portal_main
        return portal_main(rest)
    if args.module == "community":
        from stackvitals.community.cli import main as community_main
        return community_main(rest)
    if args.module == "init":
        from stackvitals.core.initcli import main as init_main
        return init_main(rest)
    if args.module == "action":
        from stackvitals.ci.cli import action_main
        return action_main(rest)
    if args.module == "ui":
        from stackvitals.core.uicli import main as ui_main
        return ui_main(rest)
    if args.module == "explain":
        from stackvitals.core.explaincli import main as explain_main
        return explain_main(rest)
    if args.module == "export":
        from stackvitals.core.exportcli import main as export_main
        return export_main(rest)
    if args.module == "project":
        from stackvitals.core.projectcli import main as project_main
        return project_main(rest)
    if args.module == "record":
        from stackvitals.core.recorded import main as record_main
        return record_main(rest)
    if args.module == "delivery":
        from stackvitals.core.deliverycli import main as delivery_main
        return delivery_main(rest)
    if args.module == "insights":
        from stackvitals.core.insightscli import main as insights_main
        return insights_main(rest)
    if args.module == "propose":
        from stackvitals.core.propose import main as propose_main
        return propose_main(rest)
    if args.module == "site":
        from stackvitals.site import main as site_main
        return site_main(rest)
    if args.module == "editor":
        from stackvitals.editors import main as editor_main
        return editor_main(rest)
    if args.module == "connectors":
        from stackvitals.connectors.check import main as connectors_main
        return connectors_main(rest)
    if args.module == "sql":
        from stackvitals.core.sqlcli import main as sql_main
        return sql_main(rest)
    if args.module == "serve":
        import logging

        from stackvitals.mcp_server import build_server
        # Request lines from the HTTP library would only clutter the AI client's log.
        logging.getLogger("httpx").setLevel(logging.WARNING)
        # The 11 core tools by default; `--tools all` (or STACKVITALS_MCP_TOOLS=all) loads every one.
        tools = args.tools or os.environ.get("STACKVITALS_MCP_TOOLS", "core")  # the command line wins over the environment
        build_server(tools="all" if tools == "all" else "core").run("stdio")
        return 0
    if rest[:1] == ["brief"]:
        import stackvitals.contribute.cli as brief_cli
        return brief_cli.main(rest[1:])
    import mergescout.cli as mergescout_cli
    return mergescout_cli.main(rest)


if __name__ == "__main__":
    raise SystemExit(main())
