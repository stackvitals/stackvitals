from mergescout.signals.bumps import parse_bump


def p(title, head="", login="dependabot[bot]"):
    return parse_bump(title, head, login)


def test_dependabot_titles_give_package_versions_and_bump_size():
    b = p("Bump lodash from 4.17.20 to 4.17.21", "dependabot/npm_and_yarn/lodash-4.17.21")
    assert (b["ecosystem"], b["package"], b["from_version"], b["to_version"], b["bump"]) == ("npm", "lodash", "4.17.20", "4.17.21", "patch")
    b = p("build(deps): bump @babel/core from 7.23.0 to 7.24.0 in /frontend", "dependabot/npm_and_yarn/frontend/babel/core-7.24.0")
    assert (b["package"], b["bump"]) == ("@babel/core", "minor")
    # Emoji prefixes, conventional-commit prefixes and security tags all occur in real repos.
    b = p("⬆ Bump mcp from 1.26.0 to 1.30.0", "dependabot/uv/mcp-1.30.0")
    assert (b["ecosystem"], b["package"], b["bump"]) == ("pypi", "mcp", "minor")
    b = p("[Security] Bump urllib3 from 1.26.5 to 1.26.18", "dependabot/pip/urllib3-1.26.18")
    assert b["security"] and b["package"] == "urllib3"
    b = p("chore(deps-dev): Bump Pytest_Asyncio from 0.21.1 to 0.23.0", "dependabot/pip/pytest-asyncio-0.23.0")
    assert (b["package"], b["bump"]) == ("pytest-asyncio", "major")  # 0.x minor steps can break, like majors
    b = p("Bump actions/checkout from 3 to 4", "dependabot/github_actions/actions/checkout-4")
    assert (b["ecosystem"], b["package"], b["bump"]) == ("actions", "actions/checkout", "major")


def test_grouped_and_range_updates_are_marked():
    b = p("Bump the npm_and_yarn group across 2 directories with 5 updates", "dependabot/npm_and_yarn/npm_and_yarn-abc123")
    assert b["grouped"] and b["package"] is None and b["ecosystem"] == "npm"
    b = p("Update pandas requirement from <2.2,>=1.5 to >=1.5,<2.3", "dependabot/pip/pandas-gte-1.5-and-lt-2.3")
    assert (b["package"], b["bump"]) == ("pandas", "range")


def test_renovate_titles_have_no_old_version_so_size_comes_from_the_wording():
    b = p("Update dependency react to v19", "renovate/react-19.x", "renovate[bot]")
    assert (b["bot"], b["package"], b["to_version"], b["from_version"], b["bump"]) == ("renovate", "react", "19", None, "major")
    b = p("chore(deps): update dependency @types/node to v20.12.7", "renovate/node-20.x", "renovate[bot]")
    assert (b["package"], b["bump"], b["ecosystem"]) == ("@types/node", "nonmajor", None)
    b = p("fix(deps): update rust crate serde to 1.0.200", "renovate/serde-monorepo", "renovate[bot]")
    assert (b["ecosystem"], b["package"]) == ("cargo", "serde")
    b = p("Update react monorepo to v19 (major)", "renovate/major-react-monorepo", "renovate[bot]")
    assert b["grouped"] and b["bump"] == "major"
    b = p("Update dependency pytest to v8.2.0 [SECURITY]", "renovate/pypi-pytest-vulnerability", "renovate[bot]")
    assert b["security"] and b["package"] == "pytest"
    assert p("chore(deps): update all non-major dependencies", "renovate/all-minor-patch", "renovate[bot]")["grouped"]
    assert p("Lock file maintenance", "renovate/lock-file-maintenance", "renovate[bot]")["grouped"]
    # A self-hosted Renovate under another name is recognised by its branch.
    assert p("Update dependency vite to v5.2.8", "renovate/vite-5.x", "acme-bot")["package"] == "vite"


def test_other_prs_are_not_bumps():
    assert p("Fix the parser", "fix-parser", "ann") is None
    assert p("Bump version to 2.0", "release-2.0", "ann") is None


# Real titles that the first version missed (800 recent bot PRs from GitHub search, 2026-10-18).
def test_real_dependabot_variants_group_suffixes_double_prefixes_and_folders():
    b = p("Bump shivammathur/setup-php from 2.37.2 to 2.40.0 in the github-actions group",
          "dependabot/github_actions/github-actions-daa083031")
    assert (b["package"], b["bump"], b["grouped"]) == ("shivammathur/setup-php", "minor", False)
    b = p("chore(ci)(deps): bump actions/checkout from 4 to 7", "dependabot/github_actions/actions/checkout-7")
    assert (b["package"], b["bump"]) == ("actions/checkout", "major")
    b = p("build(deps): bump tokio from 1.53.2 to 1.53.3 in /python in the python-crate-minor-and-patch group",
          "dependabot/cargo/python/python-crate-minor-and-pat")
    assert (b["ecosystem"], b["package"], b["bump"]) == ("cargo", "tokio", "patch")
    b = p("Bump proxy-addr from 2.0.7 to 2.0.8 in /18 React Functional Components I/Sprint-Challenge-", "dependabot/npm_and_yarn/18-Re")
    assert (b["package"], b["bump"]) == ("proxy-addr", "patch")
    assert p("Dépendances: Bump the outils-de-developpement group with 3 updates", "dependabot/npm_and_yarn/outils-7b")["grouped"]
    assert p("build(deps): bump tinypool, @vitest/coverage-v8, @vitest/ui and vitest", "dependabot/npm_and_yarn/multi-33")["grouped"]
    assert p("chore(deps): bump sharp in /client", "dependabot/npm_and_yarn/client/multi-206ef61285")["grouped"]


def test_real_renovate_variants_ranges_suffixes_arrows_and_setup_prs():
    r = "renovate[bot]"
    b = p("build(deps): update dependency uuid from ^14.0.0 to v14.0.3", "renovate/uuid-14.x-lockfile", r)
    assert (b["package"], b["from_version"], b["to_version"], b["bump"]) == ("uuid", "^14.0.0", "14.0.3", "patch")
    b = p("fix(deps): update dependency satori to ^0.57.0", "renovate/satori-0.x", r)
    assert (b["package"], b["to_version"], b["bump"]) == ("satori", "^0.57.0", "nonmajor")
    b = p("Update dependency harper.js to ^2.13.0 - autoclosed", "renovate/harper.js-2.x", r)
    assert b["package"] == "harper.js" and b["closed_by_bot"]
    b = p("deps: Update dependency react to v19.3.1 (main)", "renovate/main-react", r)
    assert (b["package"], b["to_version"]) == ("react", "19.3.1")
    b = p("feat(container)!: Update image docker.io/library/postgres (17.6 ➔ 18.6)", "renovate/docker.io-library-postgres-18.x", r)
    assert (b["ecosystem"], b["package"], b["from_version"], b["bump"]) == ("docker", "docker.io/library/postgres", "17.6", "major")
    b = p("build(deps): update module github.com/jackc/pgx/v5 from v5.10.0 to v5.11.0", "renovate/github.com-jackc-pgx-v5-5.x", r)
    assert (b["ecosystem"], b["package"], b["bump"]) == ("go", "github.com/jackc/pgx/v5", "minor")
    b = p("chore(deps): update helm release cert-manager to v1.21.2", "renovate/cert-manager-1.x", r)
    assert (b["ecosystem"], b["package"]) == ("helm", "cert-manager")
    # Setting Renovate up, migrating its config or pinning versions is not an upgrade.
    for title in ("Configure Renovate", "chore: Configure Renovate - autoclosed", "chore(config): migrate Renovate config",
                  "chore(deps): pin dependencies"):
        assert p(title, "renovate/configure", r) is None
