# Roadmap

What comes next, in rough order. Dates are when the data allows a result, not promises. Suggestions are welcome as
issues; the ones backed by a real repo's problem move up.

## Checks already running, read on a date

- **Does the issue finder pick issues outsiders get merged?** Its ranking was frozen and its picks recorded before the
  outcomes existed. Read from 2027-03-20, when the attempt and merge windows have closed
  ([bench/accuracy/contribute](../bench/accuracy/contribute/README.md)).
- **Do agents answer older CI failures better with StackVitals?** On failures inside GitHub's 90-day log retention it
  added nothing measurable. The test that matters is on failures whose logs GitHub has deleted; it runs once enough of
  the recorded failures have passed GitHub's 90-day retention ([bench/accuracy/agents](../bench/accuracy/agents/README.md)).

## Accuracy

- A person's audit of a sample of every card's labels; today two model families label and no person has checked.
- Status precision for flaky CI: re-running pinned commits to confirm flakes directly, not only from history.
- Deployment detection for shipping workflows with plain names (docker, pypi, CD), the weak side of today's rule.

## Coverage

- Bors and other merge bots outside GitHub's merge queue; monorepo task runners (Nx, Turborepo, Bazel) that skip
  unchanged tests; GitHub Enterprise Server. Each is untested today ([limitations.md](limitations.md#failure-modes)).
- Dependency dossiers beyond npm and PyPI, and dependency paths from poetry and pip lockfiles.
- GitLab merge requests, deployments and incidents (CI already runs inside GitLab).

## Not planned

- A hosted service or an account: the suite stays in your repo.
- Productivity scores for individuals. Where StackVitals names people (an owner, who acts next on a pull request), it
  is to route work, not to rate them.
