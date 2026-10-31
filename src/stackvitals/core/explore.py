"""explore.html: SQL in the browser over the data branch's summaries, with DuckDB-WASM (pinned, integrity-checked) and
saved queries that are DevLake's own dashboard SQL on DevLake-shaped tables. On Pages it reads the files from GitHub's
raw host (Pages serves only docs/); `stackvitals ui` serves it next to the data, which it then reads directly."""
import json
from pathlib import Path

from stackvitals.core.export import COLUMNS, _sql_text
from stackvitals.core.summary import TYPES

DUCKDB = "1.32.0"
ARROW = "17.0.0"
# jsDelivr's SHA-256 of each file of the pinned release; a changed file is refused by the browser.
SRI = {"duckdb-browser.mjs": "sha256-T4wLs8I9HsRXpFHMJ0GFl7mkDddyzOrMQ2ost7mknBg=",
       "duckdb-browser-eh.worker.js": "sha256-+KtytrkLOtgwd9R0JtSpnV2aTH4Hy6GivjfWVa3Hwas=",
       "duckdb-eh.wasm": "sha256-TCIb+lnBHyTb11DnDJC5JS7KbuxWM5Nuai7HZuVf2Hk=",
       "duckdb-browser-mvp.worker.js": "sha256-sDhwJ/F04rYMLVz6Mc7MqbidipdiNGtkSaeEzRxN3jw=",
       "duckdb-mvp.wasm": "sha256-Rdcqgfuo5XaT2JDag3xwQTEOOF51YZqFWYObFTiN/pc="}
DORA_TITLES = {"deployment_frequency": "DORA: deployment frequency", "lead_time": "DORA: median lead time for changes (hours)",
               "change_failure_rate": "DORA: change failure rate", "recovery": "DORA: failed deployment recovery time (hours)",
               "monthly": "DORA: monthly deployments", "pr_cycle_time": "PR cycle time by month (hours)"}
# More of DevLake's panels, ported like the DORA ones (GitHub, Engineering Overview and Contributor Experience dashboards);
# Apache DevLake's SQL, Apache License 2.0 (see NOTICE).
DEVLAKE_MORE = [
    ("GitHub: share of closed PRs that were never merged",
     "select count(distinct case when status = 'CLOSED' then id else null end) / count(distinct case when status in "
     "('CLOSED', 'MERGED') then id else null end) as ratio\nfrom pull_requests pr\nwhere created_date between "
     "TIMESTAMP '{{FROM}}' and TIMESTAMP '{{TO}}'"),
    ("GitHub: mean time to merge by month (days)",
     "with _prs as (\n  select date_trunc('month', created_date) as time, avg((epoch(merged_date) - epoch(created_date)) / 86400) "
     "as time_to_merge\n  from pull_requests\n  where created_date between TIMESTAMP '{{FROM}}' and TIMESTAMP '{{TO}}'\n  group by 1)\n"
     "select strftime(time, '%B %Y') as _time, time_to_merge as \"Time to Merge\" from _prs order by time"),
    ("Engineering Overview: PRs merged by month",
     "with _merged_prs as (\n  select date_trunc('month', pr.merged_date) as time, count(distinct pr.id) as pr_merged_count\n"
     "  from pull_requests pr join project_mapping pm on pr.base_repo_id = pm.row_id and pm.\"table\" = 'repos'\n"
     "  where pm.project_name in ('{{PROJECT}}') and pr.merged_date is not null\n"
     "    and pr.merged_date between TIMESTAMP '{{FROM}}' and TIMESTAMP '{{TO}}'\n"
     "    and pr.merged_date >= date_trunc('month', TIMESTAMP '{{FROM}}') + INTERVAL 1 MONTH\n  group by time)\n"
     "select strftime(time, '%B %Y') as month, pr_merged_count from _merged_prs order by time"),
    ("Contributor Experience: PRs closed without merging, last month (%)",
     "select 100 * count(distinct case when status = 'CLOSED' then id else null end) / count(distinct case when status in "
     "('CLOSED', 'MERGED') then id else null end) as ratio\nfrom pull_requests pr\nwhere cast(created_date as date) between "
     "date_trunc('month', current_date) - INTERVAL 1 MONTH and date_trunc('month', current_date) - INTERVAL 1 DAY"),
]
OURS = [
    ("Pull requests merged per week, with median pickup (people)",
     "select date_trunc('week', cast(merged_at as timestamp)) as week, count(*) as merged,\n"
     "  round(median(pickup_s) / 3600, 1) as median_pickup_hours\nfrom prs where merged_at is not null and author_kind = 'person'\n"
     "group by 1 order by 1"),
    ("Insiders and outside contributors",
     "select role, count(*) as prs, count(merged_at) as merged, round(median(pickup_s) / 3600, 1) as median_pickup_hours\n"
     "from prs where author_kind = 'person' group by 1 order by 2 desc"),
    ("Flakiest CI jobs",
     "select workflow, job, state, flake_events, runs, round(flake_rate * 100, 1) as flake_pct, prs_affected, retry_minutes\n"
     "from ci_jobs order by flake_events desc, failures desc limit 20"),
    ("Tests that fail most",
     "select test_id, state, failures, flake_events, runs, message from tests order by failures desc limit 20"),
    ("Biggest open pull requests",
     "select number, author_kind, role, additions + deletions as lines, created_at from prs where status = 'OPEN'\n"
     "order by lines desc limit 20"),
]


def queries() -> list[dict]:
    dora = []
    for chunk in _sql_text().split("-- panel: ")[1:]:
        name, body = chunk.split("\n", 1)
        dora.append({"group": "DevLake dashboards", "title": DORA_TITLES[name.strip()], "sql": body.strip().rstrip(";")})
    return (dora + [{"group": "DevLake dashboards", "title": t, "sql": s} for t, s in DEVLAKE_MORE]
            + [{"group": "StackVitals summaries", "title": t, "sql": s} for t, s in OURS])


PAGE = r"""
<p class=mut>SQL over this repo's StackVitals data, run in your browser by DuckDB (WebAssembly, loaded from jsDelivr at a
pinned version with integrity hashes the first time you run a query; about 35 MB, then cached). Nothing is sent anywhere.
The saved queries marked DevLake are Apache DevLake's own dashboard SQL, ported to DuckDB and run on DevLake-shaped
tables of this repo; the dates and the DORA report fill in their time range.</p>
<p>From <input type=date id=sv-from> to <input type=date id=sv-to> DORA report
<select id=sv-report><option>2023</option><option>2021</option></select></p>
<div id=sv-saved></div>
<p><textarea id=sv-sql rows=12 style="width:100%;font-family:monospace">select * from prs limit 20</textarea></p>
<p><button id=sv-run>Run</button> <button id=sv-link type=button>Copy a link to this query</button>
<input id=sv-name placeholder="Name it" aria-label="Name for the saved query" size=18> <button id=sv-save type=button>Save in this browser</button>
<span id=sv-status class=mut></span></p>
<div id=sv-mine></div>
<div class=tbl><table id=sv-result class=find></table></div>
<p class=mut>Tables: <span id=sv-tables>reading the list...</span></p>
<script type="importmap">{"imports": {"apache-arrow": "https://cdn.jsdelivr.net/npm/apache-arrow@__ARROW__/+esm"}}</script>
<script type="module">
const REPO = __REPO__, SRI = __SRI__, COLUMNS = __COLUMNS__, TYPES = __TYPES__, QUERIES = __QUERIES__;
const BASE = "https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@__DUCKDB__/dist/";
const $ = (id) => document.getElementById(id);
const status = (text) => { $("sv-status").textContent = text; };
const today = new Date();
$("sv-to").value = today.toISOString().slice(0, 10);
$("sv-from").value = new Date(today.getTime() - 90 * 864e5).toISOString().slice(0, 10);
let source = null, conn = null;

async function where() {
  // Beside the page (Pages, public repos), next to the data (stackvitals ui, a clone), else GitHub's raw files.
  if (source) return source;
  for (const base of ["summary/", "../summary/"]) {
    try {
      const local = await fetch(base + "manifest.json", {cache: "no-store"});
      if (local.ok) return (source = [base, await local.json()]);
    } catch (e) { /* not served here */ }
  }
  const raw = `https://raw.githubusercontent.com/${REPO}/stackvitals-data/summary/`;
  const res = await fetch(raw + "manifest.json", {cache: "no-store"});
  if (!res.ok) throw new Error("No summaries found in this repo's stackvitals-data branch yet.");
  return (source = [raw, await res.json()]);
}

async function connect() {
  if (conn) return conn;
  status("Loading DuckDB...");
  const duckdb = await import(BASE + "duckdb-browser.mjs");
  const bundle = await duckdb.selectBundle({
    mvp: {mainModule: BASE + "duckdb-mvp.wasm", mainWorker: BASE + "duckdb-browser-mvp.worker.js"},
    eh: {mainModule: BASE + "duckdb-eh.wasm", mainWorker: BASE + "duckdb-browser-eh.worker.js"}});
  const file = (url) => url.split("/").pop();
  const workerText = await (await fetch(bundle.mainWorker, {integrity: SRI[file(bundle.mainWorker)]})).text();
  const wasm = await (await fetch(bundle.mainModule, {integrity: SRI[file(bundle.mainModule)]})).arrayBuffer();
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), new Worker(URL.createObjectURL(new Blob([workerText], {type: "text/javascript"}))));
  await db.instantiate(URL.createObjectURL(new Blob([wasm], {type: "application/wasm"})));
  const c = await db.connect();
  await c.query("create table calendar_months as select strftime(m, '%y/%m') as month, cast(m as date) as month_timestamp " +
                "from range(TIMESTAMP '2000-01-01', TIMESTAMP '2100-01-01', INTERVAL 1 MONTH) t(m)");
  conn = c;
  conn.db = db;
  return conn;
}

const loaded = new Set();

async function need(sql) {
  // Only the tables a query names are read (a busy repo's 23 MB of summaries took 4 s all at once, 0.2 s per query after).
  const c = await connect();
  const [base, manifest] = await where();
  const files = Object.keys(manifest.files || {}).filter((n) => /^[a-z0-9_]+\.jsonl$/.test(n));
  const named = (t) => new RegExp(`\\b${t}\\b`, "i").test(sql);
  for (const name of files) {
    const table = name.replace(/\.jsonl$/, "");
    const dl = table.startsWith("devlake_") ? table.slice(8) : null;
    const as = dl && COLUMNS[dl] ? dl : table;
    if (loaded.has(as) || !named(as)) continue;
    status(`Reading ${as}...`);
    const text = await (await fetch(base + name, {cache: "no-store"})).text();
    await c.db.registerFileText(name, text);
    // Fixed types (DevLake's, or ours for prs, ci_jobs and tests), so an all-empty column is still a number or a time.
    const types = dl && COLUMNS[dl] ? COLUMNS[dl] : TYPES[table];
    if (types) {
      const spec = Object.entries(types).map(([k, t]) => `'${k}': '${t}'`).join(", ");
      await c.query(text.trim() ? `create table "${as}" as select * from read_json('${name}', format='newline_delimited', columns={${spec}})`
        : `create table "${as}" (${Object.entries(types).map(([k, t]) => `"${k}" ${t}`).join(", ")})`);
    } else {
      await c.query(text.trim() ? `create table "${table}" as select * from read_json_auto('${name}', format='newline_delimited')`
        : `create table "${table}" (empty boolean)`);
    }
    loaded.add(as);
  }
  for (const [dl, cols] of Object.entries(COLUMNS)) {
    // No Delivery data yet: empty tables, so DevLake's queries answer N/A instead of failing.
    if (!loaded.has(dl) && named(dl)) {
      await c.query(`create table ${dl} (${Object.entries(cols).map(([k, t]) => `"${k}" ${t}`).join(", ")})`);
      loaded.add(dl);
    }
  }
  return c;
}

function fill(sql) {
  return sql.replaceAll("{{FROM}}", $("sv-from").value + " 00:00:00").replaceAll("{{TO}}", $("sv-to").value + " 23:59:59")
    .replaceAll("{{PROJECT}}", REPO.replaceAll("'", "''")).replaceAll("{{REPORT}}", $("sv-report").value);
}

function cell(value, type) {
  if (value === null || value === undefined) return "";
  if (/Timestamp|Date/.test(type)) return new Date(Number(value)).toISOString().replace(".000Z", "Z");
  if (typeof value === "bigint") return value.toString();
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(4).replace(/0+$/, "").replace(/\.$/, "");
  return String(value);
}

async function run() {
  const table = $("sv-result");
  table.textContent = "";
  try {
    const sql = fill($("sv-sql").value).trim().replace(/;\s*$/, "");
    const c = await need(sql);
    status("Running...");
    const started = performance.now();
    const result = await c.query(sql);
    const fields = result.schema.fields;
    const head = table.insertRow();
    for (const f of fields) { const th = document.createElement("th"); th.textContent = f.name; head.appendChild(th); }
    const rows = result.toArray();
    for (const r of rows.slice(0, 1000)) {
      const tr = table.insertRow();
      for (const f of fields) tr.insertCell().textContent = cell(r[f.name], String(f.type));
    }
    status(`${rows.length} row${rows.length === 1 ? "" : "s"} in ${Math.round(performance.now() - started)} ms` +
           (rows.length > 1000 ? " (first 1000 shown)" : ""));
  } catch (e) {
    status("Error: " + (e && e.message ? e.message : e));
  }
}

const saved = $("sv-saved");
let group = null;
for (const q of QUERIES) {
  if (q.group !== group) { group = q.group; const h = document.createElement("h3"); h.textContent = group; saved.appendChild(h); }
  const b = document.createElement("button");
  b.textContent = q.title;
  b.style.margin = "0 6px 6px 0";
  b.onclick = () => { $("sv-sql").value = q.sql; run(); };
  saved.appendChild(b);
}
$("sv-run").onclick = run;

// Your own queries, kept in this browser only (storage can be off: then they last until the tab closes).
const KEY = "sv-explore:" + REPO;
let mine = [];
try { mine = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch { mine = []; }
function keep() { try { localStorage.setItem(KEY, JSON.stringify(mine)); } catch { /* storage off */ } }
function showMine() {
  const box = $("sv-mine");
  box.textContent = "";
  if (!mine.length) return;
  const h = document.createElement("h3");
  h.textContent = "Your queries";
  box.appendChild(h);
  mine.forEach((q, i) => {
    const b = document.createElement("button");
    b.textContent = q.title;
    b.style.margin = "0 2px 6px 0";
    b.onclick = () => { $("sv-sql").value = q.sql; run(); };
    const x = document.createElement("button");
    x.textContent = "×";
    x.title = "Forget " + q.title;
    x.setAttribute("aria-label", "Forget " + q.title);
    x.style.margin = "0 10px 6px 0";
    x.onclick = () => { mine.splice(i, 1); keep(); showMine(); };
    box.append(b, x);
  });
}
$("sv-save").onclick = () => {
  const title = $("sv-name").value.trim() || "Query " + (mine.length + 1);
  mine = [...mine.filter((q) => q.title !== title), { title, sql: $("sv-sql").value }];
  keep();
  showMine();
  status("Saved in this browser as " + title + ".");
};
// A link that opens this page with the query ready to run: other pages link here the same way to drill down.
$("sv-link").onclick = async () => {
  const url = location.href.split("#")[0] + "#sql=" + encodeURIComponent($("sv-sql").value);
  try { await navigator.clipboard.writeText(url); status("Link copied."); } catch { status(url); }
};
showMine();
// Loaded, never run: a link from someone else is read before it runs, and a broken one leaves the page working.
if (location.hash.startsWith("#sql=")) {
  try {
    $("sv-sql").value = decodeURIComponent(location.hash.slice(5));
    status("Query from the link: read it, then run it.");
  } catch { status("The link's query couldn't be read."); }
}
where().then(([base, m]) => {
  $("sv-tables").textContent = Object.entries(m.files || {}).map(([n, f]) =>
    `${n.replace(/\.jsonl$/, "").replace(/^devlake_/, "")} (${f.rows} rows)`).join(", ") +
    (base.startsWith("http") ? " - read from GitHub" : " - read from this folder");
}, (e) => { $("sv-tables").textContent = e.message; });
</script>
"""


def render(repo: str, pages=()) -> str:
    from stackvitals import shell
    body = (PAGE.replace("__REPO__", json.dumps(repo)).replace("__SRI__", json.dumps(SRI))
            .replace("__COLUMNS__", json.dumps(COLUMNS)).replace("__TYPES__", json.dumps(TYPES)).replace("__QUERIES__", json.dumps(queries()).replace("</", "<\\/"))
            .replace("__DUCKDB__", DUCKDB).replace("__ARROW__", ARROW))
    return shell.page("Explore", repo, "explore.html", "SQL over this repo's data, in your browser.", body, pages)


def write_explore(root: Path, repo: str) -> bool:
    """docs/explore.html (it says when there are no summaries yet); rewritten only when its text changes (no churn)."""
    from stackvitals import shell
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    path = docs / "explore.html"
    text = render(repo, shell.present(docs) | {"explore.html"})
    try:
        if path.read_text(encoding="utf-8") == text:
            return False
    except OSError:
        pass
    path.write_text(text, encoding="utf-8", newline="\n")
    return True
