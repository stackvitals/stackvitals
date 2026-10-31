#!/usr/bin/env bash
# Middleware and StackVitals on the DevLake side-by-side's five repos (preregistration.md). Needs MW_PAT and GH_TOKEN.
set -euo pipefail
OUT=bench/accuracy/middleware/out
mkdir -p "$OUT"
REPOS=$(python -c "import json;print(' '.join(json.load(open('bench/accuracy/devlake/repos.json'))['drawn']))")
FROM=$(python -c "import datetime as d,urllib.parse as u;print(u.quote((d.datetime.now(d.timezone.utc)-d.timedelta(days=90)).strftime('%Y-%m-%dT00:00:00+00:00')))")
TO=$(python -c "import datetime as d,urllib.parse as u;print(u.quote(d.datetime.now(d.timezone.utc).strftime('%Y-%m-%dT00:00:00+00:00')))")
start=$(date +%s)
docker volume create middleware_postgres_data >/dev/null; docker volume create middleware_keys >/dev/null
docker pull -q middlewareeng/middleware:latest
docker inspect --format '{{.Id}} {{.Size}}' middlewareeng/middleware:latest > "$OUT/image.txt"
docker run -d --name middleware -p 3333:3333 -p 9696:9696 -p 9697:9697 -e DEFAULT_SYNC_DAYS=90 \
  -v middleware_postgres_data:/var/lib/postgresql/data -v middleware_keys:/app/keys middlewareeng/middleware:latest
until curl -sf localhost:9696/ >/dev/null && curl -sf localhost:3333/api/auth/session >/dev/null; do sleep 5; done
echo "start_s $(( $(date +%s) - start ))" > "$OUT/timing.txt"
curl -s -H "Authorization: Bearer $MW_PAT" https://api.github.com/rate_limit | python -c "import json,sys;print('remaining_before',json.load(sys.stdin)['rate']['remaining'])" >> "$OUT/timing.txt"
ORG=$(curl -s localhost:3333/api/auth/session | python -c "import json,sys;print(json.load(sys.stdin)['org']['id'])")
curl -s -X POST "localhost:3333/api/resources/orgs/$ORG/integration" -H 'content-type: application/json' \
  -d "{\"provider\":\"github\",\"the_good_stuff\":\"$MW_PAT\"}" > /dev/null
for full in $REPOS; do
  owner=${full%/*}; name=${full#*/}
  rid=$(gh api "repos/$full" --jq .id)
  curl -s -X POST "localhost:3333/api/resources/orgs/$ORG/teams/v2" -H 'content-type: application/json' -d "{
    \"name\":\"$name\",\"org_repos\":{\"$owner\":[{\"idempotency_key\":\"$rid\",\"deployment_type\":\"PR_MERGE\",
    \"provider\":\"github\",\"slug\":\"$name\",\"name\":\"$name\",\"repo_workflows\":[]}]}}" > /dev/null
done
t0=$(date +%s); curl -s -X POST localhost:9697/sync > /dev/null; echo "sync_s $(( $(date +%s) - t0 ))" >> "$OUT/timing.txt"
curl -s "localhost:3333/api/resources/orgs/$ORG/teams/v2" > "$OUT/teams.json"
for team in $(python -c "import json;print(' '.join(t['id']+':'+t['name'] for t in json.load(open('$OUT/teams.json'))['teams']))"); do
  id=${team%%:*}; name=${team#*:}
  for p in deployment_frequency lead_time change_failure_rate mean_time_to_recovery lead_time/prs deployment_analytics; do
    curl -s "localhost:9696/teams/$id/$p?from_time=$FROM&to_time=$TO" > "$OUT/mw-$name-${p//\//_}.json"
  done
done
curl -s -H "Authorization: Bearer $MW_PAT" https://api.github.com/rate_limit | python -c "import json,sys;print('remaining_after',json.load(sys.stdin)['rate']['remaining'])" >> "$OUT/timing.txt"
docker stats --no-stream middleware > "$OUT/footprint.txt"; docker system df >> "$OUT/footprint.txt"
for full in $REPOS; do
  name=${full#*/}
  stackvitals delivery "$full" --days 90 --json > "$OUT/sv-$name.json" || true
done
