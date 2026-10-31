"""The suite's typed entities, with Apache DevLake's domain names and enums (so its SQL runs on our exports) and
OpenTelemetry's attribute names for CI/CD and VCS columns. Built from the records the modules already store, so nothing
is collected twice; new code reads these, old code keeps its dicts until it moves over."""
from dataclasses import dataclass, field

from stackvitals.core.actors import kind_of
from stackvitals.core.time import secs

PR_STATES = ("OPEN", "MERGED", "CLOSED")
# DevLake's cicd result and status enums; GitHub's conclusions fold into them.
CICD_RESULTS = {"success": "SUCCESS", "failure": "FAILURE", "timed_out": "FAILURE", "startup_failure": "FAILURE",
                "cancelled": "ABORT", "action_required": "MANUAL"}
# GitHub's own word for each result, for DevLake's original_result column.
ORIGINAL = {"SUCCESS": "success", "FAILURE": "failure", "ABORT": "cancelled", "MANUAL": "action_required"}
ISSUE_TYPES = ("REQUIREMENT", "BUG", "INCIDENT")
INCIDENT_LABELS = ("incident", "outage", "sev1", "sev2", "p0")
BUG_LABELS = ("bug", "defect", "regression")
EVENT_KINDS = {"ready": "READY", "draft": "DRAFT", "req": "REVIEW_REQUEST", "unreq": "REVIEW_REQUEST_REMOVED",
               "review": "REVIEW", "merged": "MERGED", "closed": "CLOSED"}


def entity_id(entity: str, repo: str, key, source: str = "github") -> str:
    # DevLake's id form: plugin:Entity:connection:id, with the repo as the connection.
    return f"{source}:{entity}:{repo}:{key}"


def cicd_result(conclusion: str | None) -> str:
    return CICD_RESULTS.get(conclusion or "", "OTHER")


@dataclass
class ChangeEvent:
    kind: str  # READY, DRAFT, REVIEW_REQUEST, REVIEW_REQUEST_REMOVED, COMMENT, REVIEW, MERGED, CLOSED
    at: str
    actor: str | None = None
    actor_kind: str = "unknown"
    state: str | None = None  # review state: APPROVED, CHANGES_REQUESTED, COMMENTED
    assoc: str | None = None
    raised: bool = False  # the review or comment asked the author something


@dataclass
class ChangeRequest:
    """DevLake's pull_requests entity with its timeline."""
    id: str
    repo: str
    number: int
    title: str
    state: str
    draft: bool
    author: str | None
    author_kind: str
    author_assoc: str | None
    created_at: str | None
    ready_at: str | None
    merged_at: str | None
    closed_at: str | None
    updated_at: str | None
    additions: int | None
    deletions: int | None
    changed_files: int | None
    base_ref: str | None
    head_ref: str | None
    head_owner: str | None
    last_commit_at: str | None
    paths: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    requested: list[str] = field(default_factory=list)
    events: list[ChangeEvent] = field(default_factory=list)
    linked_issue: bool = False

    @classmethod
    def from_flow(cls, rec: dict, repo: str) -> "ChangeRequest":
        from stackvitals.flow.analyze import ready_at
        events = []
        for e in rec.get("ev") or []:
            kind = EVENT_KINDS.get(e[0])
            if not kind:
                continue
            actor = e[2] if len(e) > 2 else None
            if e[0] == "review":
                events.append(ChangeEvent(kind, e[1], actor, kind_of(actor, e[5] if len(e) > 5 else None), e[3],
                                          e[4] if len(e) > 4 else None, bool(e[6]) if len(e) > 6 else False))
            else:
                events.append(ChangeEvent(kind, e[1], actor, kind_of(actor) if actor else "unknown"))
        for c in rec.get("cm") or []:
            if c and c[0]:
                events.append(ChangeEvent("COMMENT", c[0], c[1], kind_of(c[1], c[3] if len(c) > 3 else None), None,
                                          c[2] if len(c) > 2 else None, bool(c[4]) if len(c) > 4 else False))
        events.sort(key=lambda e: e.at)
        return cls(entity_id("PullRequest", repo, rec["n"]), repo, rec["n"], rec.get("ti") or "", rec.get("st") or "OPEN",
                   bool(rec.get("draft")), rec.get("au"), kind_of(rec.get("au"), rec.get("at")), rec.get("as"), rec.get("cr"),
                   ready_at(rec), rec.get("mg"), rec.get("cl"), rec.get("up"), rec.get("add"), rec.get("del"), rec.get("files"),
                   rec.get("base"), rec.get("head"), rec.get("ho"), rec.get("lc"), list(rec.get("paths") or []),
                   list(rec.get("lb") or []), list(rec.get("rq") or []), events, bool(rec.get("iss")))

    def to_devlake(self) -> dict:
        # DevLake's pull_requests columns, so its dashboards' SQL runs on an export of ours.
        return {"id": self.id, "pull_request_key": self.number, "title": self.title, "status": self.state,
                "author_name": self.author, "author_id": entity_id("Account", self.repo, self.author or "") if self.author else None,
                "created_date": self.created_at, "merged_date": self.merged_at, "closed_date": self.closed_at,
                "additions": self.additions, "deletions": self.deletions, "is_draft": self.draft,
                "base_ref": self.base_ref, "head_ref": self.head_ref,
                "url": f"https://github.com/{self.repo}/pull/{self.number}"}


@dataclass
class Step:
    number: int | None
    name: str | None
    result: str
    started_at: str | None
    finished_at: str | None


@dataclass
class Task:
    """DevLake's cicd_tasks: one job of a run attempt."""
    id: str
    name: str | None
    result: str
    created_at: str | None
    started_at: str | None
    finished_at: str | None
    labels: list[str] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)

    @property
    def duration_s(self) -> float | None:
        return secs(self.started_at, self.finished_at)


@dataclass
class PipelineRun:
    """DevLake's cicd_pipelines: one attempt of a workflow run."""
    id: str
    repo: str
    run_id: int
    attempt: int
    name: str | None
    path: str | None
    trigger: str | None
    branch: str | None
    sha: str | None
    tree: str | None
    change_numbers: list[int]
    head_owner: str | None
    result: str
    created_at: str | None
    started_at: str | None
    updated_at: str | None
    tasks: list[Task] = field(default_factory=list)

    @classmethod
    def from_ci(cls, run: dict, jobs: list[dict], repo: str) -> "PipelineRun":
        key = f"{run['id']}:{run.get('att', 1)}"
        tasks = [Task(entity_id("CicdTask", repo, f"{key}:{j['id']}"), j.get("n"), cicd_result(j.get("c")), j.get("cr"),
                      j.get("st"), j.get("en"), list(j.get("lb") or []),
                      [Step(s[0], s[1], cicd_result(s[2]), *(list(s[3:5]) + [None, None])[:2]) for s in j.get("steps") or []])
                 for j in jobs if j.get("run") == run["id"] and j.get("att", 1) == run.get("att", 1)]
        return cls(entity_id("CicdPipeline", repo, key), repo, run["id"], run.get("att", 1), run.get("wfn"), run.get("path"),
                   run.get("ev"), run.get("br"), run.get("sha"), run.get("tree"), list(run.get("pr") or []), run.get("ho"),
                   cicd_result(run.get("c")), run.get("cr"), run.get("st"), run.get("up"), tasks)

    def to_devlake(self, scope: str) -> dict:
        """DevLake's cicd_pipelines row, its cicd_tasks rows (this attempt's jobs) and its cicd_pipeline_commits row."""
        whole = lambda s: None if s is None else int(round(s))  # noqa: E731
        url = f"https://github.com/{self.repo}/actions/runs/{self.run_id}" + (f"/attempts/{self.attempt}" if self.attempt > 1 else "")
        pipeline = {"id": self.id, "name": self.name, "result": self.result, "status": "DONE",
                    "original_status": "completed", "original_result": ORIGINAL.get(self.result, self.result.lower()),
                    "duration_sec": whole(secs(self.started_at, self.updated_at)),
                    "queued_duration_sec": whole(secs(self.created_at, self.started_at)), "created_date": self.created_at,
                    "queued_date": self.created_at, "started_date": self.started_at, "finished_date": self.updated_at,
                    "environment": None, "type": None, "cicd_scope_id": scope, "display_title": self.name, "url": url}
        tasks = [{"id": t.id, "name": t.name, "pipeline_id": self.id, "result": t.result, "status": "DONE",
                  "original_status": "completed", "original_result": ORIGINAL.get(t.result, t.result.lower()), "type": None,
                  "environment": None, "duration_sec": whole(t.duration_s), "queued_duration_sec": whole(secs(t.created_at, t.started_at)),
                  "started_date": t.started_at, "finished_date": t.finished_at, "created_date": t.created_at,
                  "queued_date": t.created_at, "cicd_scope_id": scope} for t in self.tasks]
        commit = {"pipeline_id": self.id, "commit_sha": self.sha, "branch": self.branch, "repo_id": scope,
                  "repo_url": f"https://github.com/{self.repo}"}
        return {"cicd_pipelines": pipeline, "cicd_tasks": tasks, "cicd_pipeline_commits": [commit] if self.sha else []}

    def to_otel(self) -> dict:
        # OpenTelemetry's CI/CD and VCS attribute names (semantic conventions, release candidate).
        return {"cicd.pipeline.name": self.name, "cicd.pipeline.run.id": self.run_id, "cicd.pipeline.run.attempt": self.attempt,
                "cicd.pipeline.result": self.result, "cicd.pipeline.run.state": "finished",
                "vcs.repository.name": self.repo, "vcs.ref.head.name": self.branch, "vcs.ref.head.revision": self.sha,
                "vcs.change.id": self.change_numbers[0] if self.change_numbers else None}


@dataclass
class TestResult:
    """One test's outcome in one run attempt, with CTRF's field names in to_ctrf()."""
    test_id: str
    status: str  # PASSED, FAILED, FLAKY, SKIPPED
    repo: str
    run_id: int
    attempt: int
    artifact: int | None = None
    suite: str | None = None
    fingerprint: str | None = None
    message: str | None = None
    duration_ms: int | None = None

    @classmethod
    def from_report(cls, rec: dict, repo: str) -> list["TestResult"]:
        run, att, art, suite = rec.get("run"), rec.get("att", 1), rec.get("art"), rec.get("name")
        slow = {tid: ms for tid, ms in rec.get("slow") or []}
        out = [cls(tid, "FAILED", repo, run, att, art, suite, fp, msg, slow.get(tid)) for tid, fp, msg in rec.get("failed") or []]
        out += [cls(tid, "FLAKY", repo, run, att, art, suite, None, None, slow.get(tid)) for tid in rec.get("flaky") or []]
        return out

    def to_ctrf(self) -> dict:
        status = {"FAILED": "failed", "FLAKY": "passed", "SKIPPED": "skipped"}.get(self.status, "passed")
        out = {"name": self.test_id, "status": status, "duration": self.duration_ms or 0, "flaky": self.status == "FLAKY",
               "suite": self.suite}
        if self.message:
            out["message"] = self.message
        return out


@dataclass
class Issue:
    """DevLake's issues: type REQUIREMENT, BUG or INCIDENT; status TODO or DONE."""
    id: str
    repo: str
    number: int
    type: str
    status: str
    created_at: str | None
    closed_at: str | None
    author: str | None
    author_kind: str
    labels: list[str] = field(default_factory=list)

    @classmethod
    def from_community(cls, rec: dict, repo: str, incident_labels=INCIDENT_LABELS, bug_labels=BUG_LABELS) -> "Issue":
        labels = [str(x).lower() for x in rec.get("lb") or []]
        kind = "INCIDENT" if any(x in labels for x in incident_labels) else "BUG" if any(x in labels for x in bug_labels) \
            else "REQUIREMENT"
        return cls(entity_id("Issue", repo, rec["n"]), repo, rec["n"], kind, "DONE" if rec.get("cl") else "TODO", rec.get("cr"),
                   rec.get("cl"), rec.get("au"), kind_of(rec.get("au"), rec.get("at")), labels)


@dataclass
class Release:
    id: str
    repo: str
    tag: str
    published_at: str | None
    sha: str | None = None


@dataclass
class Deployment:
    """DevLake's cicd_deployment_commits: a successful production deployment of one commit."""
    id: str
    repo: str
    sha: str | None
    finished_at: str | None
    source: str  # workflow, api, release
    environment: str = "PRODUCTION"
    result: str = "SUCCESS"
    name: str | None = None

    @classmethod
    def new(cls, repo: str, key: str, sha: str | None, finished_at: str | None, source: str, name: str | None = None) -> "Deployment":
        return cls(entity_id("CicdDeployment", repo, key), repo, sha, finished_at, source, name=name)


@dataclass
class Incident:
    """An incident (issue labelled incident, a revert or a hotfix PR) linked to the deployment before it, or to none."""
    id: str
    repo: str
    opened_at: str | None
    resolved_at: str | None
    source: str  # issue, revert, hotfix
    deployment_id: str | None = None

    @classmethod
    def new(cls, repo: str, key: str, opened_at: str | None, resolved_at: str | None, source: str,
            deployment_id: str | None = None) -> "Incident":
        return cls(entity_id("Incident", repo, key), repo, opened_at, resolved_at, source, deployment_id)
