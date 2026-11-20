# Persistent GitHub sign-in

The secure dashboard runs as a small Cloudflare Worker with a D1 session store.
GitHub Pages continues to publish the match schedule and static UI. Once
`docs/auth-config.json` points at the verified HTTPS Worker, the old launch URL
opens that dashboard automatically. Frontend assets and API calls then share an
origin, avoiding reliance on third-party cookies on Safari/iPhone.

## Account and permissions

Register a private GitHub App owned by `soojh007`, requesting only repository
**Actions: read/write** and **Metadata: read**. Install it on **Only select
repositories → football-shorts-factory**. No Contents write, organization access,
YouTube credentials, Sportmonks token or OpenAI key is needed by the dashboard.
The owner and repository are also checked by immutable numeric IDs server-side.
The OAuth token exchange is restricted to the configured repository ID.

## Deployment and one-time registration

Requirements: an authorized Cloudflare account, Node 22 or newer, and the existing
Python environment for the local registration helper. Use the free-tier resources
unless the account owner explicitly chooses a paid configuration.

1. Sign in with `npx wrangler@4 login` using the Cloudflare account's original
   login method. There is no reason to grant unrelated AI, email, browser or
   container permissions; this deployment uses Workers and D1.
2. In `auth-worker/wrangler.jsonc`, retain the configured repository/owner IDs.
   Provision the `football-shorts-auth` D1 binding (Wrangler supports automatic
   provisioning), then apply `auth-worker/schema.sql` to it. Deploy the Worker,
   obtain its HTTPS origin, and set `APP_ORIGIN` to that exact origin before
   deploying again. Read/write session APIs fail closed until secrets are set.
3. Run from the repository root:

   ```bash
   python scripts/setup-github-app.py --origin https://YOUR-DASHBOARD.workers.dev
   ```

   Open the printed loopback URL. Review the private App manifest on GitHub.
   The helper checks a one-use state, converts the registration code once, and
   passes `GITHUB_CLIENT_ID`, `GITHUB_CLIENT_SECRET` and a random 256-bit
   `TOKEN_ENCRYPTION_KEY` to `wrangler secret bulk` through stdin. It never logs
   secret values or writes them to source/browser storage. It discards the
   unused installation private key. Keep it running if hosting authorization
   needs to be completed before credential delivery can finish.
4. Install the App on the single repository, then visit the deployed dashboard
   and click **Sign in with GitHub**. Registration/installation requires the
   account owner's approval. `request_oauth_on_install` is intentionally disabled
   so authorization uses this app's own state and PKCE-protected login flow.
5. Verify live login, reload, sign-out and unauthorized access before changing
   `docs/auth-config.json`. A build or mock OAuth test alone does not verify this.
   Store only the public origin in that JSON; never put a token or client secret
   in any file under `docs/`.

Example database commands (run inside `auth-worker` after account login):

```bash
npx wrangler d1 create football-shorts-auth
# Add the returned public database ID to the DB binding in wrangler.jsonc.
npx wrangler d1 execute football-shorts-auth --remote --file schema.sql
npx wrangler deploy
```

If the helper's secret delivery fails, credentials remain only in that running
process. Complete Cloudflare authentication and reload its original setup URL to
retry delivery; do not register a second App. Once delivery succeeds, the helper
clears its credential dictionary. Losing the process before delivery requires
reviewing the existing App in GitHub settings and generating a new client secret.

## Sessions and workflow requests

- OAuth uses state bound to an HttpOnly browser cookie and PKCE S256. Server-side
  state is consumed atomically and expires after ten minutes.
- The browser receives a random opaque `__Host-` session cookie with `Secure`,
  `HttpOnly`, `SameSite=Lax`, no Domain attribute and up to 30 days lifetime.
  Clearing cookies, signing out, expiry or revoked authorization can require
  signing in again. Closing/reloading the page does not log out the server session.
- Access and rotating refresh tokens are encrypted with AES-256-GCM in D1, bound
  to the session hash. They never appear in frontend JSON, HTML or storage.
  Refresh uses an atomic database lease. Uncertain refreshes require re-login
  rather than replaying a possibly consumed refresh token.
- POST requests require same-origin Origin and a session-bound CSRF token.
  Server checks the trusted published schedule and the next-two-hour window.
  Repository, workflow, branch, automatic readiness waiting and private-production
  defaults are owned by the server, not supplied by the browser.
- A database reservation prevents duplicate dispatches across tabs/reloads.
  Ambiguous dispatches remain uncertain and are not automatically retried.
  Failed job review/reruns remain available through GitHub Actions.
- Signing out deletes the server session. GitHub App authorization can also be
  revoked in GitHub settings. This service has no endpoint that accepts a PAT.

GitHub Pages' existing memory-only token fallback is preserved until the secure
service has been verified and the public configuration is enabled. It does not
silently start saving PATs in localStorage, sessionStorage or IndexedDB.

## Checks

```bash
node --test auth-worker/test/*.test.mjs tests/test_session_client.mjs tests/test_workflow_client.mjs
npx wrangler@4 deploy --dry-run --config auth-worker/wrangler.jsonc --outdir dist
```

Tests use an in-memory SQLite D1 adapter, mock GitHub OAuth/API responses and
synthetic credentials. No real workflow is dispatched by tests. Browser/live
OAuth verification and initial App installation require the real account owner.

References: [GitHub App login flow](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/generating-a-user-access-token-for-a-github-app),
[App manifests](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest),
[Cloudflare secrets](https://developers.cloudflare.com/workers/configuration/secrets/).
