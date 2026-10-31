from stackvitals.core.config import parse
from stackvitals.flow.automate import DOCS_LABEL, plan

ON = {"review_requests": True, "size_labels": True, "docs_label": True}


def pr(n, add=5, dele=0, paths=("src/a.py",), labels=(), draft=False, au="ann"):
    return {"n": n, "add": add, "del": dele, "paths": list(paths), "lb": list(labels), "draft": draft, "au": au, "rq": []}


def test_team_automation_is_off_until_each_part_is_turned_on():
    cfg, notes = parse("")
    assert all(cfg["automation"][k] is False for k in ON) and not notes
    cfg, notes = parse("[automation]\nsize_labels = true\n")
    assert cfg["automation"]["size_labels"] is True and cfg["automation"]["review_requests"] is False


def test_size_labels_are_set_and_a_stale_one_replaced():
    acts, _state = plan([pr(1, add=3), pr(2, add=400, dele=150, labels=["size/S"])], [], ON, {})
    adds = {(a["n"], tuple(a["body"]["labels"])) for a in acts if a["kind"] == "label"}
    assert (1, ("size/XS",)) in adds and (2, ("size/L",)) in adds
    assert any(a["kind"] == "unlabel" and a["n"] == 2 and a["label"] == "size/S" for a in acts)
    assert not [a for a in plan([pr(3, add=3, labels=["size/XS"])], [], ON, {})[0] if a["n"] == 3]


def test_docs_only_prs_get_the_low_risk_label_and_lose_it_when_code_comes_in():
    acts, _ = plan([pr(1, paths=["docs/x.md", "README.md"]), pr(2, paths=["src/a.py", "docs/x.md"], labels=[DOCS_LABEL])],
                   [], ON, {})
    assert any(a["kind"] == "label" and a["n"] == 1 and DOCS_LABEL in a["body"]["labels"] for a in acts)
    assert any(a["kind"] == "unlabel" and a["n"] == 2 and a["label"] == DOCS_LABEL for a in acts)


def test_one_suggested_reviewer_is_requested_once_and_never_on_drafts_or_bots():
    queue = [{"n": 1, "suggested": [{"login": "bo"}, {"login": "cy"}]}, {"n": 2, "suggested": [{"login": "bo"}]},
             {"n": 3, "suggested": [{"login": "bo"}]}, {"n": 4, "suggested": []}]
    prs = [pr(1), pr(2, draft=True), pr(3, au="dependabot[bot]"), pr(4)]
    acts, state = plan(prs, queue, ON, {})
    asks = [a for a in acts if a["kind"] == "review"]
    assert [(a["n"], a["body"]["reviewers"]) for a in asks] == [(1, ["bo"])]
    assert state["requested"] == [1]
    # Asked once: a request someone took back isn't sent again.
    assert not [a for a in plan(prs, queue, ON, state)[0] if a["kind"] == "review"]


def test_turned_off_parts_do_nothing_and_writes_are_capped():
    off = {"review_requests": False, "size_labels": False, "docs_label": False}
    assert plan([pr(1, paths=["docs/a.md"])], [{"n": 1, "suggested": [{"login": "bo"}]}], off, {})[0] == []
    many = [pr(n) for n in range(100)]
    assert len(plan(many, [], ON, {})[0]) <= 40


def test_the_docs_label_needs_every_file_read_and_never_takes_code_named_like_docs():
    # Review findings: requirements.txt and README.py counted as docs; a PR with 80 files was judged on its first 50.
    from stackvitals.flow.automate import DOCS, plan
    assert not any(DOCS.search(f) for f in ("requirements.txt", "CMakeLists.txt", "README.py", "LICENSE_check.go"))
    assert all(DOCS.search(f) for f in ("README.md", "docs/notes.txt", "LICENSE", "guide.rst"))
    p = {"n": 1, "paths": ["a.md"] * 50, "files": 80, "add": 1, "del": 1, "au": "x", "at": "User", "lb": []}
    assert plan([p], [], {"docs_label": True}, {})[0] == []
    assert plan([{**p, "files": 50}], [], {"docs_label": True}, {})[0][0]["kind"] == "label"
