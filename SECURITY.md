# Security

## Reporting a problem

Please report security problems privately, through GitHub's "Report a vulnerability" button on this repository's
Security tab, not in a public issue. Say what you found, how to reproduce it and what it affects. You'll get an answer
within 7 days, and a fix or a plan within 30 days for anything that lets a token, a key or private data reach someone
who shouldn't have it.

## What counts

- A token or key reaching a host or a person it shouldn't.
- Private data (a private repo's names, titles, logs, people) reaching a public data branch, page, comment or file.
- Text from a stranger (a fork PR, an issue, a test name) that pings people, plants links or changes what StackVitals
  does.
- Anyone without the right access changing settings, decisions or other repos.
- History on the `stackvitals-data` branch lost or corrupted.

How StackVitals guards each of these, with the test that checks it: [docs/threat-model.md](docs/threat-model.md). What
it sends anywhere: [docs/privacy.md](docs/privacy.md).

## Supported versions

The newest release. Fixes are released as a new version; pin the Action to a release tag or commit.

## Releases

Each release's files are built in GitHub Actions, signed keylessly with Sigstore and published with a software bill of
materials and a build provenance attestation, so you can check a download came from this repository's workflow.
