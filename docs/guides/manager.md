# StackVitals for an engineering manager

You want to know where your team's time goes and whether changes help, without rating people. This is the path.

## First week

1. **Set it up** on each of your team's repos ([quickstart](../quickstart.md)), or on one repo first. It reads up to
   90 days of CI and a year of pull requests on the first run, so you start with history, not an empty page.
2. **Open Insights** in the app: one list of what to fix first across CI, reviews and delivery, ranked by hours at
   stake ([modules](../modules.md#insights-what-to-fix-first)). Start at the top.
3. **Read Delivery** for cycle time in LinearB's phases (coding, pickup, review, deploy) and DORA's five metrics (the industry's standard delivery measures: how often you deploy, how long a change takes to ship, how often a change fails, and how fast you recover). Before you share a DORA number,
   read [the DORA guide](../dora-guide.md): what each number can't tell, how it gets gamed, and why it is never for
   individual reviews.

## Every week

- The **weekly digest** (Monday, one comment on a pinned issue; to post it to chat too, set the `webhook` input, then `channels = ["issue", "webhook"]` under `[digest]`) says what
  changed. It reports a change only when it stands out from how much your repo's weeks usually swing, so false alarms
  are rare, but a quiet digest means nothing stood out, not that nothing moved: on small repos even large slowdowns
  can go unflagged ([modules](../modules.md#decide-on-github-hear-back-every-week)).
- **Working agreements** you set under `[agreements]` (first review within a day, PRs under 400 lines) are previewed
  week by week before you turn them on, then counted in the digest.
- The digest asks three **pulse** questions by reaction; StackVitals shows only the counts (GitHub itself shows who
  reacted to anyone who can see the issue).

## Questions you'll be asked

- **"Did AI tools help?"** Delivery compares AI-assisted pull requests with others from the same repo, month and size.
  Raw comparisons mislead: on public repos a 9-point gap all but disappears once compared like with like
  ([AI card](../../bench/accuracy/ai/README.md)). The result is an association, never a cause.
- **"How do we compare?"** Benchmarks are against similar public repos, with the sample size beside each.
- **"Can I see this per person?"** No. StackVitals names people only to route work (an owner, who acts next).

## Across several teams

Ask your platform team for the Portal's org view: every repo's figures added up, with the repos leading each
problem ([platform guide](platform.md)).
