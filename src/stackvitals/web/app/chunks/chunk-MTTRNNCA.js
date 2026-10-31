import{d as p}from"./chunk-G7NGB5UX.js";p();var m="stackvitals/stackvitals@v0",E=".github/workflows/stackvitals.yml",l=["ci","flow","deps","community"],f=`name: StackVitals
on:
  workflow_run:
    workflows: {names}   # your CI workflows; each finished run is read right away
    types: [completed]
  schedule:
    - cron: "17 */3 * * *"   # Team Flow every 3 hours, and a CI catch-up
  repository_dispatch:
    # Sent by \`stackvitals record\` from any deploy tool, or as CDEvents (0.4 and 0.5); for Flux add your
    # "Kustomization/<name>.<namespace>" here.
    types: [stackvitals-deployment, stackvitals-incident,
            dev.cdevents.service.deployed.0.3.0, dev.cdevents.service.upgraded.0.3.0, dev.cdevents.service.rolledback.0.3.0,
            dev.cdevents.incident.detected.0.3.0, dev.cdevents.incident.resolved.0.3.0,
            dev.cdevents.service.deployed.0.2.0, dev.cdevents.service.upgraded.0.2.0, dev.cdevents.service.rolledback.0.2.0,
            dev.cdevents.incident.detected.0.2.0, dev.cdevents.incident.resolved.0.2.0]
  workflow_dispatch:
    inputs:
      request:
        description: "A change sent from the StackVitals app (leave empty for a normal run)"
        required: false
        default: ""
  push:                      # your settings file applies at once; adding this file starts the first run
    paths: [".github/stackvitals.toml", ".github/workflows/stackvitals.yml"]
  issues:
    types: [opened, closed, reopened]  # requests from the app; flaky-test issues closed as not planned, or reopened
  issue_comment:
    types: [created]         # /stackvitals commands
  pull_request:              # the dependency check, only when a lockfile changes (never runs the PR's code)
    paths: ["**/*.lock", "**/*lock.json", "**/*lock.yaml", "**/npm-shrinkwrap.json", "**/requirements*.txt", "**/go.mod",
            "**/*.lockfile", "**/pom.xml", "**/pylock*.toml", "**/Package.resolved", "**/gems.locked",
            "**/verification-metadata.xml", "**/*.freeze"]
permissions:
  contents: write        # saves history to the stackvitals-data branch; settings changes asked for from the app
  actions: read          # reads your CI runs, jobs and test reports (write: [automation] rerun_flaky re-runs known flakes)
  checks: read           # Team Flow: sees which PRs have failing checks (write: [automation] verdict_check)
  statuses: read
  deployments: read      # Team Flow: delivery from deployments
  issues: write          # the weekly digest, answers to /stackvitals commands, flaky-test and alert issues
  pull-requests: write   # reads PRs for Team Flow; one comment on failed PR runs (set to read to turn comments off)
jobs:
  vitals:
    # Only what concerns StackVitals starts a runner: settings pushed to the default branch, requests and commands from
    # people with access to the repo, and flaky-test issues being closed or reopened.
    if: >-
      (github.event_name != 'push' || github.ref_name == github.event.repository.default_branch) &&
      (github.event_name != 'issues' ||
        (github.event.action == 'opened' && contains(github.event.issue.body, '\`\`\`stackvitals') &&
         contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.issue.author_association)) ||
        (github.event.action != 'opened' && contains(github.event.issue.labels.*.name, 'flaky-test'))) &&
      (github.event_name != 'issue_comment' ||
        (contains(github.event.comment.body, '/stackvitals') &&
         contains(fromJSON('["OWNER", "MEMBER", "COLLABORATOR"]'), github.event.comment.author_association))) &&
      (github.event_name != 'workflow_run' || !github.event.repository.private ||
        github.event.workflow_run.conclusion != 'success' || vars.STACKVITALS_EVERY_CI_RUN == 'true')
    # Private repos pay for Actions minutes: a CI run that passed starts no job (the 3-hourly run reads it), unless the
    # repo variable STACKVITALS_EVERY_CI_RUN is "true" (the verdict check needs it). On the job, so events it skips never
    # wait in (or cancel) the queue; PR checks and Test connection runs never wait for (or get dropped behind) data runs.
    concurrency:
      group: stackvitals-\${{ github.event.pull_request.number || (contains(github.event.inputs.request, '"check"') && format('check-{0}', github.run_id)) || 'data' }}
      cancel-in-progress: false
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: {ref}
        env:
          STACKVITALS_EVERY_CI_RUN: \${{ vars.STACKVITALS_EVERY_CI_RUN }}
        with:
          modules: ci,flow,deps,community
          jira-email: \${{ secrets.JIRA_EMAIL }}        # optional: Jira Cloud (see Integrations); unused while unset
          jira-token: \${{ secrets.JIRA_API_TOKEN }}
          linear-token: \${{ secrets.LINEAR_API_KEY }}  # optional: Linear
          pagerduty-token: \${{ secrets.PAGERDUTY_API_KEY }}       # optional: PagerDuty or incident.io incidents
          incident-io-token: \${{ secrets.INCIDENT_IO_API_KEY }}
          triage-key: \${{ secrets.GEMINI_API_KEY }}     # optional: a model's view on undecided failures ([ci.triage])
          # traffic-token: \${{ steps.app.outputs.token }}   # optional: keep traffic past GitHub's 14 days (see docs/modules.md)
`;function g(s){return JSON.stringify(s).replace(/[\u007f-￿]/g,e=>e==="\x7F"?e:"\\u"+e.charCodeAt(0).toString(16).padStart(4,"0"))}function v(s){let e=null;for(let t=0;t<s.length;t++){let n=s[t];if((n==='"'||n==="'")&&(e===null||e===n))e=e?null:n;else if(n==="#"&&e===null&&(t===0||/\s/.test(s[t-1])))return s.slice(0,t).replace(/\s+$/,"")}return s}var k=s=>s.length-s.replace(/^\s+/,"").length;function b(s,e){let t=new Set(e),n=(...o)=>o.some(r=>t.has(r)),i=s.match(/[^\n]*\n|[^\n]+$/g)||[],a=[],c=null;for(let o of i){let r=o.trim().split(":",1)[0],u=k(o);if(c!==null){if(u>c||!o.trim())continue;c=null}if(u===2&&(r==="workflow_run"&&!t.has("ci")||r==="pull_request"&&!t.has("deps"))){c=u;continue}if(u===2&&["actions","checks","statuses","deployments","pull-requests"].includes(r)){if(!{actions:t.has("ci"),checks:n("ci","flow"),statuses:n("ci","flow"),deployments:t.has("flow"),"pull-requests":!0}[r])continue;r==="pull-requests"&&!n("ci","flow")&&(o=`  pull-requests: read    # the dependency check reads the files a pull request changes
`)}o.trim().startsWith("modules:")&&(o=o.split("modules:")[0]+"modules: "+l.filter(d=>t.has(d)).join(",")+`
`),a.push(o)}return a.join("")}function R(s,e={}){let t="["+(s&&s.length?s:["CI"]).map(g).join(", ")+"]",n=f.replace("{names}",t).replace("{ref}",e.ref||m),i=e.modules||l;return i.join(",")!==l.join(",")&&(n=b(n,i)),e.compact?(n=n.replace(/types: \[stackvitals-deployment, stackvitals-incident,[^\]]*\]/,"types: [stackvitals-deployment, stackvitals-incident]"),n.split(/\r?\n/).map(v).filter(a=>a.trim()).join(`
`)+`
`):n}function I(s,e){let t=[];return e.days&&e.days!==90&&t.push(`days: "${Math.round(e.days)}"`),e.budget&&e.budget!==800&&t.push(`budget: "${Math.round(e.budget)}"`),e.pages==="artifact"&&t.push("pages: artifact"),t.length?s.replace(/^( *)modules: .*$/m,(n,i)=>[n,...t.map(a=>i+a)].join(`
`)):s}var y=/\b(test|tests|testing|ci|build|builds|lint|check|checks|pre-commit|e2e|unit|integration|verify|validate)\b/i,_=/\b(lock|stale|label|labeler|greet|welcome|release|publish|deploy|pages|codeql|scorecard|zizmor|dependabot|triage|sync|review)\b/i;function $(s){let e=s.filter(t=>y.test(t)&&!_.test(t));return e.length?e:s.slice()}function T(s,e){let t=l.filter(n=>e.includes(n));return`stackvitals init ${s}${t.length===l.length?"":` --modules ${t.join(",")}`}`}var N="actions/setup-go@b7ad1dad31e06c5925ef5d2fc7ad053ef454303e # v7.0.0",h="astral-sh/setup-uv@c18668ad3cf93ea998bef934396af7bb5c839dc7 # v10.2.0";function A(s=6,e=!0){let[t,n]=m.split("@"),i=" ".repeat(s),a=i+"    ";return[`${i}- uses: ${e?h:h.split(" # ")[0]}`,`${i}  with:`,`${i}    cache-dependency-glob: ""`,`${i}- name: Install StackVitals`,...e?[`${i}  # The same code and pinned packages as the StackVitals Action (its uv.lock), run from their own folder.`]:[],`${i}  run: |`,...[`git clone -q --depth 1 --branch ${n} https://github.com/${t}.git "$RUNNER_TEMP/stackvitals"`,'uv sync --quiet --frozen --only-group action --project "$RUNNER_TEMP/stackvitals"','mkdir -p "$RUNNER_TEMP/bin"','cat > "$RUNNER_TEMP/bin/stackvitals" <<EOF',"#!/bin/sh",'PYTHONPATH="$RUNNER_TEMP/stackvitals/src" exec "$RUNNER_TEMP/stackvitals/.venv/bin/python" -m stackvitals "\\$@"',"EOF",'chmod +x "$RUNNER_TEMP/bin/stackvitals"','echo "$RUNNER_TEMP/bin" >> "$GITHUB_PATH"'].map(c=>a+c)]}export{m as a,E as b,l as c,g as d,R as e,I as f,$ as g,T as h,N as i,A as j};
