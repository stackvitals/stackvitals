from stackvitals.core.pulse import QUESTIONS, ask, section, tally


class Api:
    repo = "o/r"

    def __init__(self, comments=(), reactions=None):
        self.comments, self.reactions, self.sent = list(comments), reactions or {}, []

    def _get(self, path, params=None):
        if path.endswith("/comments"):
            return self.comments
        cid = int(path.split("/comments/")[1].split("/")[0])
        return [{"content": c} for c in self.reactions.get(cid, [])]

    def send(self, method, path, body=None):
        self.sent.append((method, path, body))
        return {"id": len(self.sent)}


def test_three_questions_are_posted_with_a_marker_for_the_week():
    api = Api()
    ask(api, 7, "2026-W43")
    assert len(api.sent) == len(QUESTIONS) == 3
    assert all(path == "/repos/o/r/issues/7/comments" and "stackvitals:pulse 2026-W43" in body["body"] for _m, path, body in api.sent)
    assert "👍" in api.sent[0][2]["body"]


def test_last_weeks_answers_are_counted_from_reactions_never_by_person():
    marker = lambda key: f"<!-- stackvitals:pulse 2026-W42 {key} -->"  # noqa: E731
    comments = [{"id": 1, "body": f"q {marker('flow')}"}, {"id": 2, "body": f"q {marker('friction')}"},
                {"id": 3, "body": "the digest"}, {"id": 4, "body": "q <!-- stackvitals:pulse 2026-W41 flow -->"}]
    api = Api(comments, {1: ["+1", "+1", "-1", "heart"], 2: ["confused"]})
    got = tally(api, 7, "2026-W42", since="2026-10-12T06:00:00Z")
    assert got == {"flow": {"yes": 2, "no": 1, "mixed": 0}, "friction": {"yes": 0, "no": 0, "mixed": 1},
                   "satisfaction": {"yes": 0, "no": 0, "mixed": 0}}
    text = section(got)
    assert "2 yes, 1 no" in text and "counts only" in text
    assert section({k: {"yes": 0, "no": 0, "mixed": 0} for k, _q in QUESTIONS}) is None


def test_on_a_public_repo_only_the_teams_own_reactions_count():
    # Review finding: anyone can react on a public repo, so a passer-by's thumbs-up moved the team's pulse.
    marker = "<!-- stackvitals:pulse 2026-W42 flow -->"

    class Who(Api):
        def _get(self, path, params=None):
            if path.endswith("/comments"):
                return self.comments
            return [{"content": "+1", "user": {"login": "ann"}}, {"content": "-1", "user": {"login": "drive-by"}}]
    got = tally(Who([{"id": 1, "body": marker}]), 7, "2026-W42", keep=lambda login: login == "ann")
    assert got["flow"] == {"yes": 1, "no": 0, "mixed": 0}
