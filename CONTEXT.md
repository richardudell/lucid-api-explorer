# Lucid API Explorer — Session Context

> Written at end of session. Read this at the start of a new session before touching any code.

---

## What this app is

An internal API workbench for Lucid Software's Customer Operations / Enterprise Support team.
It lets support engineers explore, execute, and debug calls against three of Lucid's API
surfaces — REST, SCIM, and MCP — from a single browser-based UI. Claude narrates every
request/response in plain language. The central design goal is educational: make the
invisible visible. Show headers, auth flows, token lifecycles, HTTP mechanics.

Stack: Python + FastAPI backend, vanilla JS + HTML/CSS frontend (no React, no build step),
served as static files by FastAPI. Start command: `python main.py`.

---

## Current state of the work

The app is **fully functional** for REST and SCIM. MCP is scaffolded but untested in
production (the mcp package's DCR flow has not been exercised end-to-end).

All code is committed and pushed to `main` on GitHub (`richardudell/lucid-api-explorer`).
The repo is clean.

### What works today
- REST API: getUser, listUsers, userEmailSearch, getUserProfile, createUser
- SCIM API: getUser, getAllUsers, createUser, modifyUser (PUT), modifyUser (PATCH)
- OAuth Token Management: refreshAccessToken, introspectAccessToken, revokeAccessToken
- Dual OAuth 2.0 flows: user token and account token, each with their own modal,
  flow log, callback route, and state
- Claude Narrative (on-demand via "Get Narrative" button)
- Follow-up questions to Claude in the Narrative tab
- Notepad "Ask Claude" — interprets freeform notes via Claude
- Terminal tab: live HTTP feed of every request/response
- Code tab: cURL and Python snippets for every executed request
- Auth flow modal: 5-step OAuth timeline with full request/response detail per step
- Token peek: `GET /auth/token-peek` returns full token state including refresh tokens
- Token-source param helpers: "Use user/account token" buttons populate token fields
  directly from server memory (tokens are never in the browser otherwise)

### What is scaffolded but not fully tested
- MCP server connection (`app/services/lucid_mcp.py`, `app/routes/mcp_api.py`)
  The frontend MCP workspace exists. The backend is written but the DCR auth flow
  has not been exercised against a real Lucid MCP instance.

---

## Architecture decisions worth knowing

### Two OAuth flows, two token slots
Lucid has two distinct authorization endpoints:
- `oauth2/authorize` → user token (acts as the signed-in user)
- `oauth2/authorizeAccount` → account token (acts as an account admin)

These produce different tokens with different scopes. Some endpoints require one,
some require the other. The app maintains both in `app/state.py` as separate fields
(`rest_access_token` vs `rest_account_access_token`). The `ENDPOINT_REGISTRY` in
`lucid_rest.py` has a `"token"` field per endpoint specifying which slot to use:
`"user"`, `"account"`, or `"client_credentials"`.

### Token storage is in-memory only — intentional
`app/state.py` holds all tokens as module-level variables. Nothing is written to disk.
This is a deliberate design choice: it keeps the auth flow visible and re-runnable,
which serves the educational purpose of the app. The tradeoff is that tokens are lost
on server restart and users must re-authenticate.

### Token management endpoints don't use Bearer auth
`refreshAccessToken`, `introspectAccessToken`, and `revokeAccessToken` authenticate
with `client_id` + `client_secret` in the request body — not a Bearer token. The
client credentials are injected server-side from `.env` and never sent to the frontend.
This is why these three endpoints have `"token": "client_credentials"` in the registry
and are handled by `_execute_token_management_call()` rather than the normal path.

### refreshAccessToken auto-updates state
After a successful `refreshAccessToken` call, `_update_state_from_token_response()`
in `lucid_rest.py` automatically saves the new token into the correct state slot
(user or account). It infers which slot by matching the incoming refresh token against
what's currently stored. This means the app stays authenticated after a refresh without
requiring a new OAuth flow.

### refresh_token requires offline_access scope
Lucid only issues a `refresh_token` in the token response if `offline_access` is
included in the requested scopes. It is NOT in the default scope lists in `.env.example`
because it must also be an approved scope on the OAuth client in the Lucid Developer
Portal — adding it without that approval causes `invalid_scope`. The `.env.example`
file has detailed comments explaining this. To enable refresh tokens:
1. Confirm `offline_access` is approved on your OAuth client in the Developer Portal
2. Add it to `LUCID_OAUTH_SCOPES` and/or `LUCID_ACCOUNT_OAUTH_SCOPES` in `.env`
3. Re-run the auth flow — the token exchange response will include `refresh_token`

### Claude Narrative is on-demand
Narrative generation was changed from auto-fire (on every execute) to manual (user
clicks "Get Narrative" button). Reason: burning Anthropic API tokens on every request
is wasteful during development/testing. The button appears after every execution.

### Topbar button naming
The buttons are named specifically:
- "Auth User Token" — initiates `oauth2/authorize` flow
- "Auth Account Token" — initiates `oauth2/authorizeAccount` flow
- "View User Token Auth Flow" — shows flow modal for user token (hidden until first auth)
- "View Account Token Auth Flow" — shows flow modal for account token (hidden until first auth)

These were renamed late in the session from less precise names ("Re-auth REST", "Auth
Account", "View auth flow"). If you see old names in any documentation, they're stale.

### tokenSource param type
A custom param type (`tokenSource`) was introduced for fields that need a raw Bearer
token value — specifically the `token` field on introspect/revoke, and the
`refresh_token` field on refreshAccessToken. Since tokens never reach the browser
during normal operation (the backend injects them), `tokenSource` renders a helper
panel with "Use user token" / "Use account token" buttons. These call `GET
/auth/token-peek` server-side and populate the field. The `tokenField` property on
the param definition controls whether the access token or refresh token is fetched.

### select param type
Also introduced for `refreshAccessToken`'s `grant_type` field. Renders a `<select>`
dropdown styled to match the dark theme. Options are defined in `param.options` in
the ENDPOINTS definition in `app.js`.

---

## File structure quick reference

```
app/
  config.py          — loads .env variables, exports constants
  state.py           — ALL in-memory runtime state lives here
  routes/
    auth.py          — OAuth flows, callbacks, /auth/status, /auth/token-peek
    rest_api.py      — POST /api/rest/:endpoint route
    scim_api.py      — POST /api/scim/:endpoint route
    mcp_api.py       — POST /api/mcp/prompt route
    ai.py            — POST /ai/narrative, /ai/followup, /ai/notepad routes
  services/
    lucid_rest.py    — ENDPOINT_REGISTRY, execute_rest_call(), token mgmt logic
    lucid_scim.py    — SCIM endpoint execution
    lucid_mcp.py     — MCP connection (DCR flow via mcp package)
    ai_client.py     — ALL Anthropic SDK calls (narrative, followup, notepad)
static/
  index.html         — full UI shell
  style.css          — dark IDE theme
  app.js             — all frontend logic (ENDPOINTS, auth, rendering, polling)
main.py              — uvicorn entry point, mounts all routers
.env                 — secrets (gitignored, never commit)
.env.example         — documented template for .env (committed)
CLAUDE.md            — instructions for Claude Code (build order, constraints)
```

---

## Known issues / things to watch

1. **`__pycache__` directories inside `app/` were committed in the first big commit.**
   The `.gitignore` now covers them going forward, but the existing tracked ones were
   removed via `git rm --cached` and committed in a follow-up. They are gone from the
   repo but will be regenerated locally by Python — that's fine, git will ignore them.

2. **Lucid scope strings use dot-notation, not colon-notation.**
   Valid: `account.user:readonly`, `user.profile`, `offline_access`
   Invalid: `users:read`, `account.users:admin.readonly` (these were tried and rejected
   with `invalid_scope` during development). See Lucid docs:
   https://developer.lucid.co/reference/access-scopes

3. **`Lucid-Api-Version: 1` header is required on all REST API calls.**
   Without it, Lucid returns HTTP 400 `invalidVersion`. This header is injected in
   `execute_rest_call()` in `lucid_rest.py`. If you add new REST endpoints, make sure
   they flow through that function and not a custom path that skips the header.

4. **MCP is untested end-to-end.** The DCR flow managed by the `mcp` Python package
   has not been exercised against a real Lucid MCP instance in this session. It may
   work, or it may need debugging. The frontend MCP workspace is complete.

5. **The `createUser` endpoint in the REST API requires the account token**, not the
   user token. This is because Lucid's account-admin operations require a token obtained
   via `oauth2/authorizeAccount`. If it returns 401, check that "Auth Account Token"
   has been completed in the topbar.

---

## What to work on next (suggested)

- **Test MCP end-to-end** — launch the app, click "Auth Account Token", then go to
  MCP workspace and submit a prompt. See what comes back and debug from there.
- **Token visibility panel** — a dedicated UI panel (maybe in the topbar or sidebar)
  that shows the current token state as a live, formatted object — type, scopes, expiry
  countdown, refresh token presence — rather than requiring a visit to `/auth/token-peek`.
- **V2 features** (per CLAUDE.md): live Lucidchart diagram generation via JSON Standard
  Import API, Gemini migration (swap internals of `ai_client.py` only), persistent
  session history via SQLite.
