# Lucid API Explorer

> REST · SCIM · MCP — powered by Claude

An internal API workbench and educational tool built for Lucid Software's Customer Operations and Enterprise Support team. It provides a unified interface for exploring, executing, and debugging Lucid API calls, with optional Claude narration and visual auth explainers.

---

## What it does

- **Executes real API calls** against Lucid's REST API, SCIM API, and MCP server from a single browser-based interface
- **Handles all three authentication models** — OAuth 2.0 Authorization Code Flow (REST), static Bearer token (SCIM), and OAuth 2.0 with Dynamic Client Registration (MCP) — with animated step-by-step explanations of each flow
- **Narrates requests with Claude on-demand** — engineers can click **Get Narrative** after a call to generate a four-beat explanation and ask follow-up questions in plain English
- **Generates Lucidchart diagrams** via the Standard Import API — describe a diagram, Claude produces the JSON, the app packages it as a `.lucid` file and uploads it directly to Lucid
- **Includes an OAuth Packet Intercept simulator** — a browser-only interactive game that shows insecure Authorization Code flow vs PKCE defense step-by-step

---

## Architecture

```
  Your Browser
       │  HTTP → localhost:8000
       ▼
  This App  (python main.py)
       │  HTTPS → Lucid APIs
       ▼
  Lucid  (REST · SCIM · MCP)
```

The app is a thin, transparent proxy. Credentials never touch the browser — tokens are injected by this app and stored in memory only. The frontend is deliberately simple (no React, no build step) so DevTools shows engineers exactly what's happening.

### Tech stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI 0.115, Uvicorn 0.32 |
| HTTP client | httpx 0.28 (async) |
| MCP client | mcp 1.26 (`OAuthClientProvider`, `streamablehttp_client`) |
| AI | Anthropic SDK 0.42, claude-sonnet-4-6 |
| Frontend | Vanilla HTML + CSS + JavaScript — no framework, no build step |
| Config | python-dotenv |

---

## Error Envelope and Correlation IDs

Most API-style backend routes now return a stable response envelope so the frontend can
reliably distinguish success vs typed failure.

### Success shape

```json
{
  "ok": true,
  "correlation_id": "uuid-or-forwarded-id",
  "data": { "...existing payload..." },
  "meta": {}
}
```

### Error shape

```json
{
  "ok": false,
  "correlation_id": "uuid-or-forwarded-id",
  "error": {
    "category": "auth_error",
    "message": "Human-readable summary",
    "retryable": false,
    "recommended_action": "reauth",
    "http_status": 401,
    "details": {},
    "upstream": {}
  }
}
```

### Error categories

- `config_error`
- `auth_error`
- `api_error`
- `rate_limit`
- `network_error`
- `model_output_error`
- `model_policy_error`
- `validation_error`
- `unknown_error`

### Correlation header behavior

- Inbound: app accepts `X-Correlation-Id` if provided by caller.
- Fallback: app generates a UUID per request when header is missing.
- Outbound: app always returns `X-Correlation-Id` response header.
- Body: `correlation_id` is included in both success and error envelopes.

Primary implementation lives in:

- `app/errors.py`
- `main.py` (correlation middleware)

Routes currently wrapped with this envelope pattern:

- `/api/rest/{endpoint_key}`
- `/api/scim/{endpoint_key}`
- `/api/mcp/prompt`
- `/api/mcp/tools`
- `/ai/narrative`
- `/ai/followup`
- `/ai/notepad`
- `/ai/standard-import`

---

## Authentication model

| Surface | Method | Credential source |
|---|---|---|
| REST API (user token) | OAuth 2.0 Authorization Code Flow | Browser redirect → Lucid consent → `/callback` |
| REST API (account token) | OAuth 2.0 Authorization Code Flow | Browser redirect → Lucid consent → `/callback-account` |
| SCIM API | Static Bearer token | `.env` → `LUCID_SCIM_TOKEN` |
| MCP server | OAuth 2.0 + Dynamic Client Registration | `mcp` package handles DCR automatically |

**On MCP auth specifically:** Unlike the REST API, where you register a `client_id` and `client_secret` once in Lucid's Developer Portal, MCP uses Dynamic Client Registration — the app POSTs its client metadata to Lucid's MCP registration endpoint at runtime and receives fresh credentials on the spot. The `mcp` Python package drives this flow via `OAuthClientProvider`. No manual portal setup is required.

All tokens are held in this app's memory only — nothing is written to disk. Tokens are lost when you stop `python main.py`. This is intentional: re-authenticating takes seconds, and keeping auth visible is the point.

---

## API surfaces covered

### REST API

| Endpoint | Method | Scope required |
|---|---|---|
| `getAccountInfo` | `GET /accounts/me` | `account.info` |
| `searchAccountDocuments` | `POST /accounts/me/documents/search` | `lucidchart.document.content:admin.readonly` |
| `searchDocuments` | `POST /documents/search` | `lucidchart.document.content:readonly` |
| `createDocument` | `POST /documents` | `lucidchart.document.content` |
| `getDocument` | `GET /documents/{documentId}` | `lucidchart.document.content:readonly` |
| `getDocumentContents` | `GET /documents/{documentId}/contents` | `lucidchart.document.content:readonly` |
| `trashDocument` | `POST /documents/{documentId}/trash` | `lucidchart.document.content` |
| `getFolder` | `GET /folders/{folderId}` | `folder:readonly` |
| `createFolder` | `POST /folders` | `folder` |
| `updateFolder` | `PATCH /folders/{folderId}` | `folder` |
| `trashFolder` | `POST /folders/{folderId}/trash` | `folder` |
| `restoreFolder` | `POST /folders/{folderId}/restore` | `folder` |
| `listFolderContents` | `GET /folders/{folderId}/contents` | `folder:readonly` |
| `listRootFolderContents` | `GET /folders/root/contents` | `folder:readonly` |
| `getUser` | `GET /users/{userId}` | `account.user:readonly` |
| `listUsers` | `GET /users` | `account.user:readonly` |
| `userEmailSearch` | `GET /users?email=...` | `account.user:readonly` |
| `getUserProfile` | `GET /users/me/profile` | `account.user:readonly` |
| `createUser` | `POST /users` | `account.user` |
| `refreshAccessToken` | `POST /oauth2/token` | — |
| `introspectToken` | `POST /oauth2/introspect` | — |
| `revokeToken` | `POST /oauth2/revoke` | — |
| `importStandardImport` | `POST /documents` (multipart) | `lucidchart.document.content` |

The app manages two separate OAuth tokens: a **user token** (for user-context endpoints like `getUser`) and an **account token** (for account-admin endpoints like `createUser` and `listUsers`). Lucid uses different authorization URLs for each, and the app handles both flows independently.

### SCIM API

| Endpoint | Method |
|---|---|
| `scimGetUser` | `GET /scim/v2/Users/{userId}` |
| `scimGetAllUsers` | `GET /scim/v2/Users` |
| `scimCreateUser` | `POST /scim/v2/Users` |
| `scimModifyUserPut` | `PUT /scim/v2/Users/{userId}` |
| `scimModifyUserPatch` | `PATCH /scim/v2/Users/{userId}` |

SCIM PATCH uses the SCIM 2.0 PatchOp schema — the app constructs the correct envelope and sets `Content-Type: application/scim+json`.

### MCP server

Natural language prompt interface via `mcp.lucid.app`. The app connects via Streamable HTTP, lists available tools from the server, and executes them based on the prompt. Tool calls and results are logged in the Terminal tab. Plain cURL cannot reproduce MCP requests — the Code tab explains why and shows the correct Python SDK usage instead.

---

## V2: Standard Import (Lucidchart diagram generation)

The `importStandardImport` endpoint exposes Lucid's [Standard Import API](https://developer.lucid.co/reference/import-lucid-file), which accepts a structured JSON document and creates a Lucidchart or Lucidspark diagram from it.

The app adds two ways to generate that JSON:

**Template gallery** — three built-in starter documents (flowchart, org chart, swimlane) that load into the editor with one click.

**Claude generation** — describe a diagram in plain English ("show how MCP auth works", "diagram the token refresh flow"), and Claude generates the Standard Import JSON. The backend validates/normalizes output, applies compatibility transforms, and attempts JSON repair when model output is malformed.

The upload is packaged as a multipart POST with a `.lucid` zip file containing `document.json` — the same format Lucid's own apps use internally. On success, the response includes the new document's URL.

### OAuth Packet Intercept Simulator

The **Simulate** tab is a browser-only educational game:

- 6-step timeline of OAuth events (internal + packet steps)
- Insecure vs PKCE toggle
- Click-to-intercept packet waves
- End states: pwned / defended / missed

This runs entirely in frontend JS/CSS (no backend calls).

---

## Claude integration

All Anthropic SDK calls are routed through a single file: `app/services/ai_client.py`. Nothing else in the codebase touches the SDK. This means a future model swap requires changing one file only.

| Function | Trigger | What Claude does |
|---|---|---|
| `generate_narrative` | "Get Narrative" button | Four-beat narrative: auth method · request · response · what it means |
| `answer_followup` | Follow-up input in narrative panel | Answers questions in context of the last API call |
| `interpret_notepad` | "Ask Claude" in sidebar notepad | Reads pasted user IDs, error codes, or notes; recommends the right endpoint |
| `generate_standard_import_json` | "Generate with Claude" in SI gallery | Produces Lucid Standard Import JSON from a plain-English prompt |

Narrative generation is **on-demand only** — Claude is not called automatically after every request. Engineers click "Get Narrative" when they want it. Bearer tokens are redacted before any data is sent to the Anthropic API.

---

## Setup

This section is written for a coworker on a **brand new MacBook** who has never used Terminal before.

### What you'll need

- A Mac running macOS
- Internet access
- A Lucid developer account with an OAuth app in [lucid.app/developer](https://lucid.app/developer)
- A Lucid admin account with SCIM token access (Admin Panel → Security → API Tokens)
- An Anthropic API key from [console.anthropic.com](https://console.anthropic.com)

### 0) Open Terminal

1. Press `Command + Space` to open Spotlight.
2. Type `Terminal`.
3. Press `Return`.

You should now see a window with a command prompt.

### 1) Install Apple's command line tools

Run:

```bash
xcode-select --install
```

- If a popup appears, click **Install**.
- If it says tools are already installed, continue.

### 2) Install Homebrew (package manager)

Copy/paste this exact command into Terminal:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After install, run this to verify:

```bash
brew --version
```

### 3) Install Git and pyenv

Run:

```bash
brew install git pyenv
```

Verify:

```bash
git --version
pyenv --version
```

### 4) Configure pyenv in your shell (one-time)

Run these commands:

```bash
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.zshrc
echo '[[ -d $PYENV_ROOT/bin ]] && export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.zshrc
echo 'eval "$(pyenv init - zsh)"' >> ~/.zshrc
source ~/.zshrc
```

### 5) Install Python 3.12 and clone the repo

Run:

```bash
pyenv install 3.12.9
git clone https://github.com/richardudell/lucid-api-explorer.git
cd lucid-api-explorer
pyenv local 3.12.9
python --version
```

`python --version` should show `3.12.x`.

### 6) Create a virtual environment and install dependencies

Run:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

When the venv is active, your prompt usually starts with `(.venv)`.

### 7) Configure environment variables

Create your local config:

```bash
cp .env.example .env
```

Open `.env` in any editor and fill these values:

| Variable | Where to get it |
|---|---|
| `LUCID_CLIENT_ID` | Lucid Developer Portal → your OAuth app |
| `LUCID_CLIENT_SECRET` | Lucid Developer Portal → your OAuth app |
| `LUCID_REDIRECT_URI` | Set to `http://localhost:8000/callback` and register this exact URI in the portal |
| `LUCID_ACCOUNT_REDIRECT_URI` | Set to `http://localhost:8000/callback-account` and register this exact URI in the portal |
| `LUCID_OAUTH_SCOPES` | Space-separated, e.g. `account.user:readonly user.profile offline_access` |
| `LUCID_ACCOUNT_OAUTH_SCOPES` | e.g. `account.user offline_access` |
| `LUCID_SCIM_TOKEN` | Lucid Admin Panel → Security → API Tokens |
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |

Notes:

- `offline_access` includes a refresh token (if that scope is enabled on your Lucid OAuth client).
- MCP needs no credentials in `.env`; it uses Dynamic Client Registration at runtime.

### 8) Run the health check, then start the app

Run:

```bash
python scripts/doctor.py
python main.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### Quickstart (returning users)

If your machine is already set up, this is enough:

```bash
git clone https://github.com/richardudell/lucid-api-explorer.git
cd lucid-api-explorer
pyenv local 3.12.9
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
cp .env.example .env
python scripts/doctor.py
python main.py
```

### Demo mode (no real secrets)

For UI walkthroughs where you only need the interface running:

```bash
cp .env.demo .env
python scripts/doctor.py --demo
python main.py
```

In demo mode, missing AI/SCIM secrets do not block startup. Those features show clear config/auth errors when invoked.

### Daily run / stop commands

Start (from repo root):

```bash
source .venv/bin/activate
python main.py
```

Stop server:

- Press `Control + C` in Terminal

### Common first-time issues

**`python: command not found`**
- Run `source ~/.zshrc`, then `python --version` again.
- Confirm you ran `pyenv local 3.12.9` inside the repo folder.

**`pip install -r requirements.txt` fails**
- Confirm `python --version` is `3.12.x`.
- Recreate venv:
  - `rm -rf .venv`
  - `python -m venv .venv`
  - `source .venv/bin/activate`
  - `python -m pip install --upgrade pip`
  - `pip install -r requirements.txt`

**Port already in use**
- Another process is using `8000`. Stop it, or change the port in `.env`:
  - set `PORT=8001`
  - then run `python main.py`
  - then open `http://localhost:8001`

> **Note:** Uvicorn auto-reload is intentionally disabled (`reload=False`). Reloading can wipe in-memory OAuth state mid-flow and cause `state_mismatch` on callbacks. Restart manually after code changes.

### Security note for tunnels (ngrok)

This tool is designed for local workstation use. If you expose it through a
tunnel (for example `ngrok`) you are exposing live OAuth/session controls and
token-bearing workflows to anyone who can reach that URL.

- Use a dedicated test tenant and least-privilege scopes.
- Never run with production credentials when a tunnel is public.
- Close the tunnel immediately after SAML testing is complete.
- Remote access is blocked by default; only set `ALLOW_REMOTE=true` when you
  intentionally need external access.

---

## Project structure

```
lucid-api-explorer/
├── main.py                        # Uvicorn entry point; FastAPI app wiring
├── requirements.txt
├── .env.example                   # Copy to .env; all variables documented inline
├── app/
│   ├── config.py                  # Loads and validates .env on startup
│   ├── state.py                   # In-memory token storage for all three surfaces
│   ├── routes/
│   │   ├── auth.py                # OAuth flows: /auth/lucid, /callback, /auth/mcp, etc.
│   │   ├── rest_api.py            # POST /api/rest/{endpoint_key}
│   │   ├── scim_api.py            # POST /api/scim/{endpoint_key}
│   │   ├── mcp_api.py             # POST /api/mcp/prompt, GET /api/mcp/tools
│   │   └── ai.py                  # POST /ai/narrative, /ai/followup, /ai/notepad, /ai/standard-import
│   └── services/
│       ├── lucid_rest.py          # REST API execution, token management, Standard Import upload
│       ├── lucid_scim.py          # SCIM API execution
│       ├── lucid_mcp.py           # MCP client: DCR, OAuth, Streamable HTTP, tool execution
│       └── ai_client.py           # ALL Anthropic SDK calls — nothing else touches the SDK
├── static/
│   ├── index.html                 # Single-page app shell
│   ├── style.css
│   └── app.js                     # All frontend logic (~4200+ lines, no framework)
└── docs/
    ├── lucid-api-explorer-PRD-final.docx
    ├── lucid-api-explorer-FLOW-final.docx
    ├── lucid-api-explorer-DESIGN-final.docx
    └── lucid-api-explorer-BACKEND-final.docx
```

---

## Design decisions

**In-memory only, nothing on disk.** Tokens live in `app/state.py` as module-level variables and are lost on restart. This keeps auth flows visible and repeatable — support engineers learn more from re-authenticating than from a cached session they didn't initiate.

**No framework, no build step.** The frontend is three files: `index.html`, `style.css`, `app.js`. FastAPI serves them as static files. No npm, no webpack, no transpilation. Engineers can read the frontend in DevTools without a source map.

**All AI calls in one file.** `app/services/ai_client.py` is the only file that imports `anthropic`. Every other file calls the functions it exposes. Swapping the model or provider means changing one file and nothing else.

**Two separate OAuth tokens for REST.** Lucid's REST API uses different authorization URLs for user-context vs account-context operations. The app manages both independently — separate flows, separate state, separate topbar indicators.

**Uvicorn reloader disabled.** `reload=False` is intentional. The reloader kills the parent process and spawns a child, which clears the CSRF state token stored between `/auth/lucid` and `/callback`, causing a `state_mismatch` error every time a file changes mid-flow.

**MCP via the official `mcp` Python package.** Rather than implementing the MCP protocol manually, the app uses `mcp 1.26` with its built-in `OAuthClientProvider`. The package handles DCR, PKCE, token attachment, Streamable HTTP transport, and token refresh. The app implements `TokenStorage` to bridge it to `app.state`.

---

## What's next

- **Persistent session history** via SQLite — replay past requests without re-executing
- **Gemini migration** — swap `app/services/ai_client.py` internals; all function signatures stay the same
- **More Standard Import templates** — decision trees, sequence diagrams, architecture maps
