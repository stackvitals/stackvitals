# StackVitals for a platform team

You run GitHub for an org and want one view of every repo, owners that are real, standards people can see coming,
and a security review you can sign off.

## Roll it out

1. **Portal first.** Create a private repo (for example `portal`) and save the workflow from
   `stackvitals portal init` in it (`stackvitals portal check my-org` first says what your token can read). With the built-in token it reads public repos; for private ones, an org
   owner creates a read-only org App (`stackvitals portal app-link my-org` opens GitHub's form filled in)
   ([modules](../modules.md#portal)).
2. **The suite per repo.** Each team adds the workflow ([quickstart](../quickstart.md)); `uvx stackvitals ci init
   OWNER/REPO` writes it with that repo's CI workflows named. Private repos set `pages: artifact` (each run that
   changed the app uploads it as a download kept 7 days) or open the app with `stackvitals ui OWNER/REPO`.
3. **Settings as code.** `.github/stackvitals.toml` per repo; every setting, its default and the permission it needs
   are in [settings.md](../settings.md).

## What the Portal gives you

- **Owners, checked:** CODEOWNERS as GitHub reads it, teams with members, people still in the org.
- **Scorecards** (bronze, silver, gold) with evidence, your own rules in `portal.toml`, and `from = <date>` so a new
  rule shows what it would say before it counts.
- **Campaigns** with a date, a tracking issue and reminders; **required checks** for a level; **golden paths** that
  open a pull request with your standard files; a **docs index**; a **Backstage** export.
- **The org view:** totals and medians of what every repo published, with the five worst repos on each.

## Security and compliance

- [Threat model](../threat-model.md): each threat, what stops it, and the test that holds it.
- [Enterprise controls](../enterprise.md): SSO, permissions, audit log and data residency all come from GitHub.
- StackVitals' own workflows pin every action to a commit, and the release workflow signs releases with Sigstore and
  adds an SBOM; pin the Action itself to a release's commit SHA ([SECURITY.md](../../SECURITY.md)).
- [What leaves your repos](../privacy.md): every outside host the code can reach, each optional.

## Scale

For busy repos (2,000 CI runs a day), CI Health alone is estimated at under 40% of the built-in token's hourly limit;
their CI history keeps about four months under the default 250 MB cap ([scaling](../scaling.md)). Portal reads about 180 to 260 repos per run with the
built-in token and continues where it stopped.
