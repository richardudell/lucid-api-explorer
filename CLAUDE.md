# Lucid API Explorer — Claude Code Instructions

## What this project is
An internal API workbench and educational tool built for Lucid Software's
Customer Operations / Enterprise Support Team. It provides a unified
interface to explore, execute, and debug calls across three of Lucid's
API surfaces: the REST API, the SCIM API, and the MCP server.

The app is designed for support engineers ranging from complete beginners
to experienced technical users. Its central educational purpose is to make
the invisible visible — showing what happens between client and server
during authentication and API calls, narrated in plain language by Claude.

Tagline: "REST, SCIM, and MCP — powered by Claude"

## Planning documents
All architectural decisions are already made and documented. Before writing
any code, read all four planning documents in /docs:

- lucid-api-explorer-PRD-final.docx      — what it is, who it's for, features
- lucid-api-explorer-FLOW-final.docx     — every user state and interaction
- lucid-api-explorer-DESIGN-final.docx   — visual language and educational layer
- lucid-api-explorer-BACKEND-final.docx  — tech stack, auth architecture, file structure

Do not deviate from decisions made in these documents without asking first.

## Tech stack (non-negotiable)
- Python + FastAPI backend only
- Static HTML + CSS + vanilla JavaScript frontend — no React, no Node.js, no build step
- Frontend served directly by FastAPI as static files
- Uvicorn as the ASGI server, called programmatically from main.py
- httpx for async HTTP requests to Lucid APIs
- mcp Python package for MCP server connection and DCR auth flow
- anthropic Python SDK for Claude narrative generation
- python-dotenv for .env loading

## Non-negotiable constraints
- Never call the Anthropic SDK directly from routes or services other than
  app/services/ai_client.py — all AI calls are routed through that file only
- Never commit .env — it is gitignored
- Token storage is in-memory only via app/state.py — nothing persists to disk
- Start command is: python main.py
- The /callback route must be implemented for REST API OAuth Authorization Code Flow

## Project structure
Follow this exact structure — do not invent new folders or files:

```
lucid-api-explorer/
├── main.py
├── .env
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
├── CLAUDE.md
├── app/
│   ├── __init__.py
│   ├── config.py
│   ├── state.py
│   ├── routes/
│   │   ├── auth.py
│   │   ├── rest_api.py
│   │   ├── scim_api.py
│   │   └── mcp_api.py
│   └── services/
│       ├── lucid_rest.py
│       ├── lucid_scim.py
│       ├── lucid_mcp.py
│       └── ai_client.py
├── static/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── docs/
└── docs/troubleshooting.md
```

## Build order — follow this sequence exactly
Build one step at a time. Stop and show output after each step. Do not
proceed to the next step until confirmed.

1. Project scaffold — create all folders, __init__.py files, requirements.txt,
   and main.py (uvicorn entry point)
2. .env.example — with all required variables and comments explaining each
3. app/config.py — loads and validates .env variables on startup
4. app/state.py — in-memory token storage for all three API surfaces
5. app/routes/auth.py — OAuth Authorization Code Flow for REST API including
   /auth/lucid (initiates flow) and /callback (receives code, exchanges for token)
6. static/index.html + style.css + app.js — full frontend shell with IDE-style
   dark layout: topbar, left sidebar (API selector + notepad), main workspace,
   and bottom panel with three tabs (Terminal, Code, Claude Narrative)
7. app/services/lucid_rest.py + app/routes/rest_api.py — REST API proxy
8. app/services/lucid_scim.py + app/routes/scim_api.py — SCIM API proxy
9. app/services/ai_client.py — Claude four-beat narrative generation and
   notepad interpretation (three functions: generate_narrative, answer_followup,
   interpret_notepad)
10. app/services/lucid_mcp.py + app/routes/mcp_api.py — MCP server connection
    via DCR auth flow (most complex — do last)
11. Wire everything together, test all routes, verify .env.example is complete

## Authentication — three surfaces, three models
- REST API: OAuth 2.0 Authorization Code Flow — requires browser redirect,
  /callback endpoint, pre-registered redirect URI in Lucid developer portal
- SCIM API: Static Bearer Token — loaded from .env, no flow required
- MCP Server: OAuth 2.0 with Dynamic Client Registration — handled by mcp
  Python package, no manual setup required

## V1 endpoints to implement
REST API: getUser, listUsers, createUser, userEmailSearch, getUserProfile,
OAuth token endpoint, OAuth authorization URL
SCIM API: getUser, getAllUsers, createUser, modifyUser (PUT), modifyUser (PATCH)
MCP: natural language prompt interface via mcp package

## Code style
- Type hints on all functions
- Async/await throughout (FastAPI is async)
- Short focused functions — one responsibility each
- Docstrings on all service functions
- Comments explaining non-obvious logic especially in auth flows

## V2 considerations (do not build now, just be aware)
- Live Lucidchart diagram generation via JSON Standard Import API
- Gemini migration — swap internals of ai_client.py only
- Persistent session history via SQLite
