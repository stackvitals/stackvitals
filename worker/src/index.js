// StackVitals instant alerts: a Cloudflare Worker an org deploys to its own free account. It receives the org's GitHub
// webhooks, checks their signature, and posts to Slack, Discord, Microsoft Teams or a JSON webhook within seconds.

const encoder = new TextEncoder();

export async function verify(secret, body, signature) {
  // GitHub signs the raw body with HMAC SHA-256 (X-Hub-Signature-256: sha256=<hex>).
  if (!secret || !signature || !signature.startsWith("sha256=")) return false;
  const key = await crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, encoder.encode(body)));
  const hex = Array.from(mac, (b) => b.toString(16).padStart(2, "0")).join("");
  const given = signature.slice(7);
  if (given.length !== hex.length) return false;
  let diff = 0;
  for (let i = 0; i < hex.length; i++) diff |= hex.charCodeAt(i) ^ given.charCodeAt(i);
  return diff === 0;
}

// Text from GitHub (titles, branch names) must never ping anyone or form links in chat.
export function plain(text) {
  return String(text ?? "")
    .replace(/[<>&]/g, (c) => ({ "<": "‹", ">": "›", "&": "and" })[c])
    .replace(/@/g, "@​")
    .replace(/\]\(/g, "]​(")
    .slice(0, 200);
}

function prRef(repo, pr) {
  return `${repo}#${pr.number} "${plain(pr.title)}"`;
}

// One short message per event worth hearing about at once; null for the rest.
export function describe(event, payload, env = {}, usual = null) {
  const repo = payload.repository?.full_name;
  const names = env.NAME_PEOPLE === "true";
  if (event === "pull_request" && payload.action === "review_requested" && payload.pull_request) {
    const pr = payload.pull_request;
    if (pr.draft) return null;
    const who = names && payload.requested_reviewer?.login ? ` from ${plain(payload.requested_reviewer.login)}` : "";
    const team = names && payload.requested_team?.name ? ` from the ${plain(payload.requested_team.name)} team` : "";
    const hint = usual ? ` (this repo usually picks up reviews within ${usual})` : "";
    return { kind: "review_requested", url: pr.html_url, text: `Review requested${who}${team} on ${prRef(repo, pr)}${hint}.` };
  }
  if (event === "pull_request_review" && payload.action === "submitted" && payload.review?.state === "approved") {
    const pr = payload.pull_request;
    return { kind: "approved", url: pr.html_url, text: `${prRef(repo, pr)} is approved and ready to merge.` };
  }
  if (event === "workflow_run" && payload.action === "completed") {
    const run = payload.workflow_run;
    const prs = run?.pull_requests || [];
    if (!prs.length || !["failure", "timed_out", "startup_failure"].includes(run.conclusion)) return null;
    const list = prs.map((p) => `#${p.number}`).join(", ");
    return { kind: "checks_failed", url: run.html_url,
      text: `${plain(run.name)} failed on ${repo} pull request ${list} (attempt ${run.run_attempt || 1}).` };
  }
  if (event === "check_suite" && payload.action === "completed") {
    const suite = payload.check_suite;
    const prs = suite?.pull_requests || [];
    // GitHub Actions suites arrive as workflow_run too; only other CI systems' suites are told here.
    if (!prs.length || suite.app?.slug === "github-actions" || suite.conclusion !== "failure") return null;
    return { kind: "checks_failed", url: `https://github.com/${repo}/pull/${prs[0].number}/checks`,
      text: `Checks from ${plain(suite.app?.name || "CI")} failed on ${repo} pull request ${prs.map((p) => `#${p.number}`).join(", ")}.` };
  }
  return null;
}

export function payloadFor(url, message) {
  const text = `${message.text} ${message.url}`;
  if (url.includes("hooks.slack.com")) return { text };
  if (url.includes("discord.com/api/webhooks") || url.includes("discordapp.com/api/webhooks")) {
    return { content: text, allowed_mentions: { parse: [] } };
  }
  if (url.includes("logic.azure.com") || url.includes("webhook.office.com") || url.includes("powerplatform.com")) {
    return { type: "message", attachments: [{ contentType: "application/vnd.microsoft.card.adaptive", content: {
      type: "AdaptiveCard", version: "1.4", $schema: "http://adaptivecards.io/schemas/adaptive-card.json",
      body: [{ type: "TextBlock", text: message.text, wrap: true }],
      actions: [{ type: "Action.OpenUrl", title: "Open on GitHub", url: message.url }] } }] };
  }
  return { source: "stackvitals", kind: message.kind, text: message.text, url: message.url };
}

function channels(env) {
  return ["SLACK_WEBHOOK_URL", "DISCORD_WEBHOOK_URL", "TEAMS_WEBHOOK_URL", "JSON_WEBHOOK_URL"].map((k) => env[k]).filter(Boolean);
}

// The repo's usual pickup time from its published Delivery file, when the repo runs StackVitals and it is public
// (or a read-only token is set); a missing file just leaves the hint out.
export async function usualPickup(repo, env, fetchImpl = fetch) {
  if (!repo || env.READ_DELIVERY === "false") return null;
  const headers = { "User-Agent": "stackvitals-worker", Accept: "application/vnd.github.raw+json" };
  if (env.GITHUB_TOKEN) headers.Authorization = `Bearer ${env.GITHUB_TOKEN}`;
  try {
    const res = await fetchImpl(`https://api.github.com/repos/${repo}/contents/docs/delivery.json?ref=stackvitals-data`, { headers });
    if (!res.ok) return null;
    const p50 = (await res.json())?.phases?.pickup?.p50_h;
    if (typeof p50 !== "number") return null;
    return p50 >= 48 ? `${(p50 / 24).toFixed(1)} days` : p50 >= 1 ? `${p50.toFixed(1)} h` : `${Math.round(p50 * 60)} min`;
  } catch {
    return null;
  }
}

// True when every job that failed in this run is one the repo's CI Health already knows as flaky (its published
// data.json), so the alert would only be noise; anything unreadable counts as a real failure.
export async function knownFlakyOnly(repo, run, env, fetchImpl = fetch) {
  if (!repo || !run?.jobs_url || env.READ_DELIVERY === "false") return false;
  const headers = { "User-Agent": "stackvitals-worker", Accept: "application/vnd.github+json" };
  if (env.GITHUB_TOKEN) headers.Authorization = `Bearer ${env.GITHUB_TOKEN}`;
  try {
    const [data, jobs] = await Promise.all([
      fetchImpl(`https://api.github.com/repos/${repo}/contents/docs/data.json?ref=stackvitals-data`,
        { headers: { ...headers, Accept: "application/vnd.github.raw+json" } }),
      fetchImpl(`${run.jobs_url}?per_page=100`, { headers })]);
    if (!data.ok || !jobs.ok) return false;
    const file = (path) => String(path || "").split("/").pop();
    const flaky = new Set(((await data.json())?.jobs || []).filter((j) => j.state === "flaky")
      .map((j) => `${file(j.workflow)} / ${j.job}`));
    const failed = ((await jobs.json())?.jobs || []).filter((j) => j.conclusion === "failure")
      .map((j) => `${file(run.path)} / ${j.name}`);
    return failed.length > 0 && failed.every((name) => flaky.has(name));
  } catch {
    return false;
  }
}

export default {
  async fetch(request, env, ctx, fetchImpl = fetch) {
    if (request.method !== "POST") return new Response("StackVitals alerts: send GitHub webhooks here.", { status: 200 });
    const body = await request.text();
    if (!(await verify(env.GITHUB_WEBHOOK_SECRET, body, request.headers.get("X-Hub-Signature-256")))) {
      return new Response("bad signature", { status: 401 });
    }
    const event = request.headers.get("X-GitHub-Event");
    let payload;
    try {
      payload = JSON.parse(body);
    } catch {
      return new Response("bad body", { status: 400 });
    }
    const repo = payload.repository?.full_name;
    const usual = event === "pull_request" && payload.action === "review_requested" ? await usualPickup(repo, env, fetchImpl) : null;
    const message = describe(event, payload, env, usual);
    if (!message) return new Response("ignored", { status: 202 });
    if (event === "workflow_run" && message.kind === "checks_failed" && env.KNOWN_FLAKES !== "off"
        && await knownFlakyOnly(repo, payload.workflow_run, env, fetchImpl)) {
      // Only known flaky jobs failed: quiet by default, or said plainly with KNOWN_FLAKES=tell.
      if (env.KNOWN_FLAKES !== "tell") return new Response("known flakes only", { status: 202 });
      message.text += " (only known flaky jobs failed)";
    }
    const sent = await Promise.all(channels(env).map((url) => fetchImpl(url, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payloadFor(url, message)),
    }).then((r) => r.ok, () => false)));
    return new Response(JSON.stringify({ kind: message.kind, sent: sent.filter(Boolean).length, channels: sent.length }), {
      status: 200, headers: { "Content-Type": "application/json" },
    });
  },
};
