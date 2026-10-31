# Governance

## Who decides

StackVitals has one maintainer today, who reviews and merges changes and cuts releases. As regular contributors
appear, each one who has landed several reviewed changes in an area over a few months is invited to maintain it.
Maintainers will be listed in a CODEOWNERS file once there is more than one.

## How decisions are made

- Day-to-day changes: a pull request and one maintainer's review.
- Anything users would notice (a rule that decides a verdict, a default, a permission the Action asks for, a new
  outside host): an issue first, open for at least a week, so people who rely on it can object.
- Disagreements are settled by evidence where there can be some. A rule changes when held-out public data shows the
  change is better, and the losses are published either way ([CONTRIBUTING.md](CONTRIBUTING.md)).

## Promises that don't change

These hold whoever maintains the project:

- **Free and open source** under the Apache License 2.0, with no paid tier that holds back a feature.
- **No hosted backend of ours.** Your data stays in your repo; nothing is sent to the project ([docs/privacy.md](docs/privacy.md)).
- **Published accuracy.** Every rule's evidence is public, including where it is weak ([docs/accuracy.md](docs/accuracy.md)).

## Security

Reported privately and handled as [SECURITY.md](SECURITY.md) describes.
