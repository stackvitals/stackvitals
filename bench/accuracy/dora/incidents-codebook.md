# Codebook: which release an incident came from

You see one regression or incident issue from a public repo: its title, its text, when it was opened, and the repo's
releases published before it (oldest first, at most 30) and the first three after. Decide which release first contained
the problem, from what the issue itself says. You don't see any rule's answer and shouldn't guess one.

## Fields

**culprit**: one of
- a release tag, copied exactly from the lists: the first release that had the problem. Examples:
  - "works in 1.2.0, broken in 1.3.0" means 1.3.0;
  - "after upgrading from 2.0 to 2.1" means 2.1;
  - "since v5.0.0" means v5.0.0;
  - "the latest release broke X", opened two days after 4.2.0 came out, means 4.2.0 only if nothing else points
    elsewhere.
  If the issue names a version that matches a tag in another form (v1.3.0 and 1.3.0, pkg@1.3.0), copy the tag.
- `none`: the problem didn't come from a release: an unreleased branch or a nightly build, the user's setup or
  environment, a third-party service, CI only, docs, or a request rather than a regression.
- `unclear`: the issue doesn't say enough to tell which release (a version named only as "the one I use" with no number,
  several candidates, or a named version that isn't in the lists).

**evidence**: at most 200 characters quoted from the issue that decided it (empty for `unclear` if nothing helped).

**confidence**: `high` when the issue says it plainly, `medium` when it takes a small inference, `low` otherwise.

## Labelling protocol

The same as the other cards: Claude labels first; Gemini 3.5 Flash-Lite labels blind with this codebook and the same
view; a third reading settles disagreements, seeing the two answers as A and B in random order. Published: links and
labels, never issue text beyond the short evidence quote. No person has audited the labels.
