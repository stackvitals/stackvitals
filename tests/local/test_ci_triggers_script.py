"""Jobs that read a PR's labels or title through a script (github-script's context.payload, or the PR fetched with the
REST API) are label gates too: their results change without a code change, so they are never flaky CI."""
from stackvitals.ci.triggers import metadata_jobs

AIOHTTP_LABELS = """name: Labels
on:
  pull_request:
    branches:
      - 'master'
    types: [labeled, opened, synchronize, reopened, unlabeled]

jobs:
  backport:
    runs-on: ubuntu-latest
    name: Backport label added
    if: ${{ github.event.pull_request.user.type != 'Bot' }}
    steps:
      - uses: actions/github-script@v9
        with:
          github-token: ${{ secrets.GITHUB_TOKEN }}
          script: |
            const pr = await github.rest.pulls.get({
              owner: context.repo.owner,
              repo: context.repo.repo,
              pull_number: context.payload.pull_request.number
            });
            if (!pr.data.labels.find(l => l.name.startsWith("backport")))
              process.exit(1);
"""

PAYLOAD_TITLE = """on:
  pull_request:
    types: [opened, edited, synchronize]
jobs:
  title:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/github-script@v7
        with:
          script: |
            if (!/^(feat|fix)/.test(context.payload.pull_request.title)) core.setFailed("bad title")
"""

CODE_ONLY = """on:
  pull_request:
    types: [labeled, synchronize]
jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - run: pytest
      - uses: actions/github-script@v7
        with:
          script: console.log(context.payload.pull_request.number)
"""


def test_label_and_title_gates_read_through_scripts_are_found():
    assert metadata_jobs(AIOHTTP_LABELS) == {"backport", "Backport label added"}
    assert metadata_jobs(PAYLOAD_TITLE) == {"title"}
    assert metadata_jobs(CODE_ONLY) == set()  # reading only the PR's number changes nothing
