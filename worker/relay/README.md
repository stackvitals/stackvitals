# StackVitals sign-in relay (Cloudflare Worker)

"Sign in with GitHub" in the StackVitals app needs one small server step: GitHub's login endpoints don't allow calls
from a web page (no CORS) and want the app's client secret. This Worker does only that step. It takes the one-time code
(with its PKCE verifier) or a refresh token from the app, adds the client id and secret, asks GitHub for the token and
hands GitHub's answer back. Everything else, including every API call, goes from the browser straight to api.github.com.

It is optional. Without it the app offers "Connect with a token" only, which works everywhere.

What it does and doesn't do:

- Answers only the origins in `ALLOWED_ORIGINS` (CORS allowlist; others get 403 and no CORS headers).
- Requires PKCE (`code_verifier`) and a `redirect_uri` on an allowed origin; any other field is dropped.
- Keeps nothing and logs no bodies; Cloudflare's observability logs are off in `wrangler.toml`.
- Never retries; GitHub's 429 passes through with its `Retry-After`. An optional Cloudflare rate limit binding can cap
  calls per address.

## 1. Make the GitHub App

GitHub, Settings, Developer settings, GitHub Apps, New GitHub App:

- **Callback URL**: the app's address exactly as served, for example `https://stackvitals.github.io/stackvitals/` (the app is that site's index.html).
- **Expire user authorization tokens**: on (tokens last 8 hours; the app refreshes them through the relay).
- **Request user authorization (OAuth) during installation**: on. **Enable Device Flow**: off. **Webhook**: off.
- **Repository permissions** (what setup and Connections use; a user's token gets at most what both the app and the user have):

| Permission | Access | Used for |
| --- | --- | --- |
| Contents | Read and write | commit `.github/workflows/stackvitals.yml`, read the stackvitals-data branch |
| Workflows | Read and write | write files under `.github/workflows` |
| Pull requests | Read and write | open a pull request when the default branch is protected |
| Actions | Read and write | start the first run and watch its jobs |
| Variables | Read and write | set `STACKVITALS_EVERY_CI_RUN` for private repos |
| Secrets | Read and write | save connector keys from Connections |
| Pages | Read and write | turn on the Pages site from `stackvitals-data` `/docs` |
| Administration | Read and write | read the repo's Actions settings |
| Metadata | Read | always on |

- **Where can this GitHub App be installed**: any account. Then install it on the repos you want to set up.

Note the **Client ID** and generate a **client secret**.

## 2. Deploy the Worker

```
cd worker/relay
npx wrangler login
npx wrangler secret put CLIENT_SECRET      # paste the client secret
npx wrangler deploy --var CLIENT_ID:Iv23li... --var ALLOWED_ORIGINS:https://stackvitals.github.io
```

(Or set `CLIENT_ID` and `ALLOWED_ORIGINS` in `wrangler.toml`.) The free plan's 100,000 requests a day is far more than
sign-ins need. Note the address, like `https://stackvitals-relay.<you>.workers.dev`.

## 3. Point the app at it

Build the app with both values; the build adds the relay to the page's Content-Security-Policy:

```
cd web
SV_RELAY=https://stackvitals-relay.<you>.workers.dev SV_CLIENT_ID=Iv23li... npm run build
```

A repo's own app.json may also carry `"auth": {"relay": "...", "client_id": "..."}`; the app uses it only when the page's
Content-Security-Policy already allows that relay.

## Test it locally

`node --test test/*.test.mjs` (Node 20 or newer; nothing to install, no network).
