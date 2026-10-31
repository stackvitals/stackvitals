# Does installing StackVitals help a repo? (pre-registered, read from 2027-07-01)

Every card in this folder tests whether StackVitals' numbers and verdicts are right. This one asks the question they
can't: do repos that install it get better, compared with similar repos that didn't? It was set up before launch, so
before any repo had installed it:

- **Pre-registered 2026-10-24** (the Action's name amended and refrozen 2026-10-30, before launch): [preregistration.md](preregistration.md) fixes who counts (public repos using the
  Action, found by code search, installed 180+ days before the read), the comparison repos (same language and star
  tier, similar pull request volume, closest review wait, up to 3 each), the outcomes (red-CI hours on the default
  branch, review wait, newcomers' return), the comparison (a difference in differences with a bootstrap range, the
  three outcomes read together with a Holm correction) and how each result is read, including "too few adopters to
  tell" under 20 included.
- **Frozen:** `study.py freeze` stored the SHA-256 of the protocol and of the scorer in `manifest.json`; `study.py
  score` refuses to run if either changed, or before 2027-07-01.
- **Read:** the Prospective tests workflow reads it on the first scheduled run after 2027-07-01 (the 2nd of January,
  April, July and October), then every three months until a read includes 20 adopters or 2028-07-01, and opens a pull
  request with whatever it shows. After that the scorer refuses to run again: the last read stands.

Installing is not using, and repos that install a tool may already be improving: matching removes only part of that.

## Reproduce

```
python bench/accuracy/adoption/study.py freeze                                   # done 2026-10-24, again 2026-10-30
GH_TOKEN=... python bench/accuracy/adoption/study.py find                        # adopters.json (code search)
GH_TOKEN=... python bench/accuracy/adoption/study.py score --crawl <crawl folder> # 2027-07-01 to 2028-07-01
```
