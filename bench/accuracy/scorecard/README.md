# StackVitals' security checks and OpenSSF Scorecard, side by side

Run 2026-10-29. 40 repos drawn from the crawl with a fixed seed (20261029): 4 per language in Python, TypeScript,
JavaScript, Go, Rust, Java, Kotlin, C#, PHP and Ruby, 100+ stars, not archived ([run.py](run.py)). Scorecard's side is
its published weekly result (api.scorecard.dev); ours runs through the GitHub API as the Action does. 24 repos had no
published Scorecard result (most) or hit GitHub's secondary rate limit on our token, so 16 were compared.

A check agrees when both say pass or both say fail. Scorecard's -1 (inconclusive) and our "can't read" are left out
of agreement and counted. Scorecard's 0-10 score is read as pass when it is 10 (dangerous workflow, pinning, binaries,
fuzzing, packaging), 9+ (token permissions), 3+ (branch protection) or above 0 (policy, signed releases, SAST, badge).

| Check | First run | After fixes | Scorecard -1 | Ours can't read |
|---|---|---|---|---|
| Dangerous-Workflow | 15 of 15 | 15 of 15 | 1 | 0 |
| Token-Permissions | 15 of 15 | 15 of 15 | 1 | 0 |
| Pinned-Dependencies | 14 of 16 | 16 of 16 | 0 | 0 |
| Branch-Protection | 2 of 3 | 2 of 3 | 6 | 13 |
| Security-Policy | 16 of 16 | 16 of 16 | 0 | 0 |
| Signed-Releases | 6 of 6 | 6 of 6 | 10 | 3 |
| SAST | 16 of 16 | 16 of 16 | 0 | 0 |
| Binary-Artifacts | 14 of 16 | 15 of 16 | 0 | 0 |
| Fuzzing | 15 of 16 | 16 of 16 | 0 | 0 |
| CII-Best-Practices | 16 of 16 | 16 of 16 | 0 | 0 |
| Packaging | 4 of 4 | 4 of 4 | 12 | 3 |
| **All** | **133 of 139** | **137 of 139** | | |

## What the first run taught us, and what changed

- **Pinning:** Scorecard also counts `pip install <name>` with no version, hashes or requirements file, global
  `npm install -g` with no version, and Dockerfile `FROM image:tag` without a digest. We counted only actions and
  `curl | sh`; now we count all three (forsun, stratos).
- **Binaries:** our extension list had `.bin`, `.war`, `.apk` and `.dmg`, which Scorecard doesn't count, and lacked
  `.whl`, `.deb` and `.rpm`, which it does. We now use Scorecard's own list (oasis-core).
- **Fuzzing:** we counted any folder named `fuzz`; rustywind's holds output-comparison scripts, not a fuzzer, and
  Scorecard was right. We now count ClusterFuzzLite, cargo-fuzz and honggfuzz targets, libFuzzer sources and Go fuzz
  tests, which also keeps oasis-core's real fuzzing counted.

## The two left, and why

- **avencera/rustywind, binaries:** Scorecard reads file contents and finds an executable with no telling extension;
  we read the file list only, to stay at one API call. Scorecard is right here.
- **exceptionless/Exceptionless.Net, branch protection:** the classic protection settings need an admin token to read.
  We say "can't read" (13 of 16 repos), where Scorecard's own docs say it counts admin-only settings as met when it
  can't read them. Where both could read rulesets, they agreed 2 of 3 times.

## Reading it

On the checks both can see, the two agree 137 times in 139 after three fixes this comparison found. Our checks also
run on private repos, keep each week's result on the data branch, and name the file, job and fix for each finding;
Scorecard's public results cover only the public repos it scans each week (16 of the 40 drawn here).
Raw results: [results-before.json](results-before.json) (first run), [results.json](results.json) (after the fixes).
