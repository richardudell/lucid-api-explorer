# Lucid API Explorer — Session Context

> Updated for current `experiment/v2-standard-import` branch state.

## What this app is

Lucid API Explorer is an internal support/education workbench for Lucid APIs:

- REST API
- SCIM API
- MCP server
- Standard Import (SI) document creation flow

Core intent: make auth + request/response mechanics visible and teachable.

## Current implementation status

### Fully working now

- REST execution engine with endpoint registry and per-endpoint token policy
- Dual OAuth flows for REST:
  - user token (`/auth/lucid` + `/callback`)
  - account token (`/auth/lucid-account` + `/callback-account`)
- SCIM execution with static bearer token from `.env`
- MCP auth and prompt execution flow (OAuth + DCR) with working UI connect/reconnect path
- AI routes:
  - narrative
  - followup
  - notepad interpretation
  - standard import JSON generation
- Standard Import upload path (`importStandardImport`):
  - frontend editor + template gallery + Claude generation
  - backend `.lucid` packaging and multipart upload to `/documents`
- OAuth Packet Intercept simulator tab UX (persistent step strip, enlarged swimlane/packets, start overlay)

### Important SI behavior right now

`app/services/lucid_rest.py` normalizes SI payloads before upload:

- fills missing page/shape IDs
- maps `label` -> `text`
- normalizes geometry to `boundingBox`
- removes fragile shape style fields
- normalizes `page.lines` from simplified `source/target` into SI line schema

There is also a fallback retry:

- If Lucid returns `400 invalid_file`, backend retries once with lines stripped.
- This preserves document creation even if connector payload validation fails.

Implication:

- Some imports may succeed without visible lines if fallback was triggered.

## Architecture notes

- Backend: FastAPI + `httpx`
- Frontend: static HTML/CSS/JS, no build step
- Tokens are stored in `app/state.py` (memory only)
- Claude SDK usage is centralized in `app/services/ai_client.py`

## Error + observability contract (new)

- Correlation ID middleware in `main.py`:
  - accepts inbound `X-Correlation-Id`
  - generates UUID when missing
  - writes `request.state.correlation_id`
  - always returns `X-Correlation-Id` header
- Shared envelope helpers in `app/errors.py`:
  - `success_response(...)` => `{ ok, correlation_id, data, meta }`
  - typed error envelope => `{ ok:false, correlation_id, error:{ category, message, retryable, recommended_action, ... } }`
- Frontend (`static/app.js`) now unwraps envelope responses and surfaces:
  - correlation ID in response viewers
  - typed error inspector chips (category, retryable, action)
  - correlation context in Terminal / Code tabs

Current wrapped routes:

- `POST /api/rest/{endpoint_key}`
- `POST /api/scim/{endpoint_key}`
- `POST /api/mcp/prompt`
- `GET /api/mcp/tools`
- `POST /ai/narrative`
- `POST /ai/followup`
- `POST /ai/notepad`
- `POST /ai/standard-import`

## Key files

- `main.py`
- `app/routes/auth.py`
- `app/routes/rest_api.py`
- `app/routes/scim_api.py`
- `app/routes/mcp_api.py`
- `app/routes/ai.py`
- `app/services/lucid_rest.py`
- `app/services/lucid_scim.py`
- `app/services/lucid_mcp.py`
- `app/services/ai_client.py`
- `static/index.html`
- `static/style.css`
- `static/app.js`

## Known caveats / watch items

1. SI connector fidelity
- Backend now tries proper line normalization, but Lucid validation can still reject connector variants.
- Fallback keeps import successful but can drop lines.

2. Python 3.14 warning
- Anthropic dependency path emits a Pydantic v1 compatibility warning on 3.14.
- App still runs, but 3.12 is safer for local dev.

3. Tokens are ephemeral by design
- Restarting `python main.py` clears auth state and MCP session tokens.

## Endpoint coverage expansion (this pass)

### REST — newly added domains

**Priority 1 — Collaboration**
- Document user collaborators: list, get, put (create/update), delete
- Document team collaborators: get, put, delete
- Folder user collaborators: list, put, delete
- Folder group collaborators: list, put, delete

**Priority 1 — Sharing**
- Document share links: get, create (POST), update (PATCH), delete
- Folder share links: get, create (POST), update (PATCH), delete
- Accept share link (POST /sharelinks/accept)

**Priority 2 — Teams**
- listTeams, createTeam, getTeam, updateTeam
- archiveTeam, restoreTeam
- listUsersOnTeam, addUsersToTeam, removeUsersFromTeam

**Priority 3 — Audit + utility**
- getAuditLogs (GET /auditlog)
- queryAuditLogs (POST /auditlog/query)
- searchFolders (POST /folders/search)
- transferUserContent (POST /users/{userId}/transfercontent)

All collaboration/sharing endpoints use the **user token**. All team and audit endpoints use the **account token**.

### SCIM — newly added

- `scimDeleteUser` — `DELETE /scim/v2/Users/{userId}`
- Groups: getGroup, getAllGroups, createGroup, modifyGroupPatch, deleteGroup
- Metadata: ServiceProviderConfig, ResourceTypes, Schemas

### Intentional deferrals

- Cloud / Data Sources / Models / Credentials — ambiguous multi-provider payloads
- Legal Holds — compliance-only, low support value
- Embedding / Unfurling / Document Picker — integration-developer features
- Subscriptions / Licenses — Admin UI is the right tool

## Immediate next-best technical improvements

1. Add explicit terminal signal when SI fallback removes lines
- Surface a clear note in UI response panel so users know why lines are missing.

2. Add SI "strict mode" toggle
- strict: fail loudly on line schema issues
- compatibility: keep retry-without-lines behavior

3. Harden line schema against Lucid docs examples
- tighten endpoint/text/lineType formatting based on official SI line spec variants.

## Git state expectation

Work is on `main`.

Main recent commit: endpoint coverage expansion (collaboration, sharing, teams, audit, SCIM groups + metadata)
