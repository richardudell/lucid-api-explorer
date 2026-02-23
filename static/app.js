/**
 * app.js — Lucid API Explorer frontend
 *
 * Vanilla JS, no build step. All state lives in this module.
 * Communicates with the FastAPI backend exclusively via fetch().
 *
 * Responsibilities:
 *  - Auth status polling and topbar updates
 *  - Sidebar surface/endpoint navigation
 *  - Workspace state management (cards → endpoint → MCP)
 *  - Parameter form rendering and validation
 *  - Request execution and response display
 *  - Terminal, Code, and Claude Narrative panel updates
 *  - Follow-up question handling
 *  - Notepad "Ask Claude" routing
 */

'use strict';

// ── Endpoint definitions ───────────────────────────────────────────────────────
// Single source of truth for every endpoint the UI knows about.

const ENDPOINTS = {
  // REST API
  getUser: {
    surface: 'rest',
    method: 'GET',
    label: 'getUser',
    urlTemplate: 'https://api.lucid.co/users/{userId}',
    description: 'Retrieve a single Lucid user record by their unique user ID.',
    scope: 'account.user:readonly',
    docsUrl: 'https://developer.lucid.co/reference/getuser',
    params: [
      { name: 'userId', label: 'User ID', type: 'string', required: true, hint: 'The Lucid user ID (e.g. 12345678)' },
    ],
  },
  listUsers: {
    surface: 'rest',
    method: 'GET',
    label: 'listUsers',
    urlTemplate: 'https://api.lucid.co/users',
    description: 'List all users in the account. Returns a paginated array.',
    scope: 'account.user:readonly',
    docsUrl: 'https://developer.lucid.co/reference/listusers',
    params: [],
  },
  userEmailSearch: {
    surface: 'rest',
    method: 'GET',
    label: 'userEmailSearch',
    urlTemplate: 'https://api.lucid.co/users?email={email}',
    description: 'Search for a user by their email address.',
    scope: 'account.user:readonly',
    docsUrl: 'https://developer.lucid.co/reference/listusers',
    params: [
      { name: 'email', label: 'Email', type: 'string', required: true, hint: 'e.g. user@example.com' },
    ],
  },
  getUserProfile: {
    surface: 'rest',
    method: 'GET',
    label: 'getUserProfile',
    urlTemplate: 'https://api.lucid.co/users/me/profile',
    description: 'Retrieve extended profile data for the currently authenticated user.',
    scope: 'account.user:readonly',
    docsUrl: 'https://developer.lucid.co/reference/getuserprofile',
    params: [],
  },
  createUser: {
    surface: 'rest',
    method: 'POST',
    label: 'createUser',
    urlTemplate: 'https://api.lucid.co/users',
    description: 'Create a new Lucid user. Requires a JSON body with user attributes.',
    scope: 'account.user',
    docsUrl: 'https://developer.lucid.co/reference/createuser',
    params: [
      {
        name: 'body',
        label: 'Request body (JSON)',
        type: 'json',
        required: true,
        hint: 'User object — must include email and other required fields',
        placeholder: '{\n  "email": "newuser@example.com",\n  "firstName": "Jane",\n  "lastName": "Doe"\n}',
      },
    ],
  },

  // OAuth Token Management
  refreshAccessToken: {
    surface: 'rest',
    method: 'POST',
    label: 'refreshAccessToken',
    urlTemplate: 'https://api.lucid.co/oauth2/token',
    description: 'Create a new access token from an authorization code, or refresh an existing token using a refresh token. client_id and client_secret are injected server-side — never exposed to the browser. On success, the new token is automatically saved to server memory.',
    scope: 'client credentials (no Bearer token)',
    docsUrl: 'https://developer.lucid.co/reference/createorrefreshaccesstoken',
    params: [
      {
        name: 'grant_type',
        label: 'grant_type',
        type: 'select',
        required: true,
        hint: 'The OAuth 2.0 grant type',
        options: [
          { value: 'refresh_token', label: 'refresh_token — exchange a refresh token for a new access token' },
          { value: 'authorization_code', label: 'authorization_code — exchange an auth code for a token' },
        ],
      },
      {
        name: 'refresh_token',
        label: 'refresh_token',
        type: 'tokenSource',
        tokenField: 'refresh_token',  // hint to token-source helper: use refresh_token, not access_token
        required: false,
        hint: 'Required when grant_type is refresh_token',
      },
      {
        name: 'code',
        label: 'code',
        type: 'string',
        required: false,
        hint: 'Required when grant_type is authorization_code — the one-time code from /callback',
      },
      {
        name: 'redirect_uri',
        label: 'redirect_uri',
        type: 'string',
        required: false,
        hint: 'Required when grant_type is authorization_code — must match the registered redirect URI',
      },
    ],
  },
  introspectAccessToken: {
    surface: 'rest',
    method: 'POST',
    label: 'introspectAccessToken',
    urlTemplate: 'https://api.lucid.co/oauth2/token/introspect',
    description: 'Retrieve metadata about an access or refresh token — whether it is active, when it expires, its scopes, and which user it belongs to.',
    scope: 'client credentials (no Bearer token)',
    docsUrl: 'https://developer.lucid.co/reference/introspectaccesstoken',
    params: [
      { name: 'token', label: 'Token', type: 'tokenSource', required: true, hint: 'The access or refresh token to inspect' },
    ],
  },
  revokeAccessToken: {
    surface: 'rest',
    method: 'POST',
    label: 'revokeAccessToken',
    urlTemplate: 'https://api.lucid.co/oauth2/token/revoke',
    description: 'Invalidate an access or refresh token. Warning: revoking either token invalidates ALL tokens from that authorization grant.',
    scope: 'client credentials (no Bearer token)',
    docsUrl: 'https://developer.lucid.co/reference/revokeaccesstoken',
    params: [
      { name: 'token', label: 'Token', type: 'tokenSource', required: true, hint: 'The access or refresh token to revoke' },
    ],
  },

  // SCIM API
  scimGetUser: {
    surface: 'scim',
    method: 'GET',
    label: 'getUser',
    urlTemplate: 'https://users.lucid.app/scim/v2/Users/{userId}',
    description: 'Retrieve a SCIM user resource by ID.',
    scope: 'scim',
    docsUrl: 'https://developer.lucid.co/reference/scim-getuser',
    params: [
      { name: 'userId', label: 'User ID', type: 'string', required: true, hint: 'The SCIM user resource ID' },
    ],
  },
  scimGetAllUsers: {
    surface: 'scim',
    method: 'GET',
    label: 'getAllUsers',
    urlTemplate: 'https://users.lucid.app/scim/v2/Users',
    description: 'List all SCIM user resources in the account.',
    scope: 'scim',
    docsUrl: 'https://developer.lucid.co/reference/scim-getallusers',
    params: [],
  },
  scimCreateUser: {
    surface: 'scim',
    method: 'POST',
    label: 'createUser',
    urlTemplate: 'https://users.lucid.app/scim/v2/Users',
    description: 'Provision a new user via SCIM.',
    scope: 'scim',
    docsUrl: 'https://developer.lucid.co/reference/scim-createuser',
    params: [
      {
        name: 'body',
        label: 'SCIM User object (JSON)',
        type: 'json',
        required: true,
        hint: 'Must conform to SCIM 2.0 User schema',
        placeholder: '{\n  "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],\n  "userName": "jdoe@example.com",\n  "name": { "givenName": "Jane", "familyName": "Doe" },\n  "emails": [{ "value": "jdoe@example.com", "primary": true }]\n}',
      },
    ],
  },
  scimModifyUserPut: {
    surface: 'scim',
    method: 'PUT',
    label: 'modifyUser (PUT)',
    urlTemplate: 'https://users.lucid.app/scim/v2/Users/{userId}',
    description: 'Replace a SCIM user resource (full update).',
    scope: 'scim',
    docsUrl: 'https://developer.lucid.co/reference/scim-modifyuser',
    params: [
      { name: 'userId', label: 'User ID', type: 'string', required: true, hint: 'SCIM user resource ID' },
      {
        name: 'body',
        label: 'SCIM User object (JSON)',
        type: 'json',
        required: true,
        hint: 'Full replacement resource',
        placeholder: '{\n  "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],\n  "userName": "jdoe@example.com"\n}',
      },
    ],
  },
  scimModifyUserPatch: {
    surface: 'scim',
    method: 'PATCH',
    label: 'modifyUser (PATCH)',
    urlTemplate: 'https://users.lucid.app/scim/v2/Users/{userId}',
    description: 'Partially update a SCIM user resource using a patch operation.',
    scope: 'scim',
    docsUrl: 'https://developer.lucid.co/reference/scim-modifyuser',
    params: [
      { name: 'userId', label: 'User ID', type: 'string', required: true, hint: 'SCIM user resource ID' },
      {
        name: 'body',
        label: 'SCIM Patch operation (JSON)',
        type: 'json',
        required: true,
        hint: 'PatchOp body per SCIM 2.0',
        placeholder: '{\n  "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],\n  "Operations": [{ "op": "replace", "path": "active", "value": false }]\n}',
      },
    ],
  },

  // MCP
  mcpPrompt: {
    surface: 'mcp',
    method: 'POST',
    label: 'prompt',
    urlTemplate: 'https://mcp.lucid.app/mcp',
    description: 'Send a natural language prompt to the Lucid MCP server.',
    scope: 'mcp',
    docsUrl: 'https://developer.lucid.co/reference/mcp',
    params: [],
  },
};

// ── App state ──────────────────────────────────────────────────────────────────
let currentEndpointKey = null;
let lastExecutionContext = null; // stored for narrative follow-up calls
let _authPollInterval = null;   // interval ID for polling during OAuth flow

// ── DOM references ─────────────────────────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// Topbar
const authDot           = $('#auth-status-dot');
const authLabel         = $('#auth-status-label');
const scopeTagsEl       = $('#scope-tags');
const btnReauth         = $('#btn-reauth');
const btnReauthAccount  = $('#btn-reauth-account');
const btnViewAccountFlow = $('#btn-view-account-flow');

// Workspace
const wsCards      = $('#workspace-cards');
const wsEndpoint   = $('#workspace-endpoint');
const wsMcp        = $('#workspace-mcp');

const breadcrumbPath  = $('#breadcrumb-path');
const endpointMethod  = $('#endpoint-method-badge');
const endpointUrl     = $('#endpoint-url');
const endpointDesc    = $('#endpoint-description');
const endpointScope   = $('#endpoint-scope');
const endpointDocs    = $('#endpoint-docs-link');
const paramFields     = $('#param-fields');
const btnExecute      = $('#btn-execute');
const responseViewer  = $('#response-viewer');
const responseStatus  = $('#response-status-badge');
const responseLatency = $('#response-latency');
const responseJson    = $('#response-json');

const btnBack     = $('#btn-back');
const btnBackMcp  = $('#btn-back-mcp');

// MCP
const mcpPromptInput    = $('#mcp-prompt-input');
const btnMcpSubmit      = $('#btn-mcp-submit');
const mcpResponseViewer = $('#mcp-response-viewer');
const mcpResponseContent = $('#mcp-response-content');

// Bottom panel
const panelTabs     = $$('.panel-tab');
const tabTerminal   = $('#tab-terminal');
const tabCode       = $('#tab-code');
const tabNarrative  = $('#tab-narrative');
const terminalOutput = $('#terminal-output');
const curlOutput    = $('#curl-output');
const pythonOutput  = $('#python-output');
const narrativeOutput  = $('#narrative-output');
const btnGetNarrative  = $('#btn-get-narrative');
const followupInput    = $('#followup-input');
const btnFollowup      = $('#btn-followup');

// Notepad
const notepad       = $('#notepad');
const btnAskClaude  = $('#btn-ask-claude');

// ── Auth status polling ────────────────────────────────────────────────────────

async function pollAuthStatus() {
  try {
    const res = await fetch('/auth/status');
    if (!res.ok) return;
    const data = await res.json();
    updateAuthUI(data);
  } catch (_) { /* server not ready yet */ }
}

function updateAuthUI(status) {
  const restOk        = status.rest.authenticated;
  const restAccountOk = status.rest_account && status.rest_account.authenticated;
  const scimOk        = status.scim.authenticated;
  const mcpOk         = status.mcp.authenticated;

  const allOk  = restOk && scimOk;
  const anyOk  = restOk || restAccountOk || scimOk || mcpOk;

  authDot.className = 'status-dot ' + (allOk ? 'dot-authenticated' : anyOk ? 'dot-partial' : 'dot-unauthenticated');
  authLabel.textContent = allOk ? 'Authenticated' : anyOk ? 'Partially authenticated' : 'Not authenticated';

  // Render scope tags for user token
  scopeTagsEl.innerHTML = '';
  if (restOk && status.rest.scopes.length) {
    status.rest.scopes.forEach(scope => {
      const tag = document.createElement('span');
      tag.className = 'scope-tag';
      tag.textContent = scope;
      scopeTagsEl.appendChild(tag);
    });
  }
  // Render scope tags for account token (with distinct style)
  if (restAccountOk && status.rest_account.scopes.length) {
    status.rest_account.scopes.forEach(scope => {
      const tag = document.createElement('span');
      tag.className = 'scope-tag scope-tag-account';
      tag.title = 'Account token scope';
      tag.textContent = scope;
      scopeTagsEl.appendChild(tag);
    });
  }
}

// Check for auth result in URL on page load (redirected back from OAuth)
async function handleOAuthRedirect() {
  const params = new URLSearchParams(window.location.search);
  const success        = params.get('auth_success');
  const error          = params.get('auth_error');
  const accountSuccess = params.get('account_auth_success');
  const accountError   = params.get('account_auth_error');

  // Always clean the URL immediately
  window.history.replaceState({}, '', '/');

  if (success || error) {
    // Render the user token flow into the Terminal tab
    switchTab('terminal');
    await renderOAuthFlowInTerminal();
    btnViewFlow.classList.remove('hidden');
    await openAuthModalWithResults();
  }

  if (accountSuccess || accountError) {
    // Render the account token flow into the Terminal tab
    switchTab('terminal');
    await renderAccountOAuthFlowInTerminal();
    btnViewAccountFlow.classList.remove('hidden');
    // Open the modal with results — same modal, account flow type
    await openAuthModalWithResults('account');
  }
}

// ── OAuth flow → Terminal renderer ────────────────────────────────────────────
// After the OAuth round-trip completes, fetch the full step log from the server
// and render it as a rich educational timeline in the Terminal tab.

async function renderOAuthFlowInTerminal() {
  try {
    const res = await fetch('/auth/flow-status');
    if (!res.ok) return;
    const data = await res.json();

    // Clear terminal and write the OAuth story
    terminalOutput.innerHTML = '';

    addTerminalSection('── OAUTH 2.0 AUTHORIZATION CODE FLOW ──────────────────────');
    addTerminalLine(new Date().toLocaleTimeString(), 'Starting flow: REST API authentication via Lucid OAuth 2.0', 'out');

    data.steps.forEach(step => {
      const ts = new Date().toLocaleTimeString();
      const isError = step.status === 'error';
      const isPending = step.status === 'pending';
      const icon = isError ? '✗' : isPending ? '…' : '✓';
      const type = isError ? 'err' : 'out';

      addTerminalSection(`STEP ${step.step} — ${step.label.toUpperCase()}`);
      addTerminalLine(ts, `${icon} ${step.label}`, type);
      addTerminalLine('', `  ${step.detail}`, type);

      // Show request details if present
      if (step.request) {
        addTerminalLine('', '', 'out');
        addTerminalLine('', '  ── REQUEST ──────────────────────────────────────────', 'out');
        if (step.request.method) {
          addTerminalLine('', `  ${step.request.method} ${step.request.url || ''}`, 'out');
        }
        if (step.request.headers) {
          Object.entries(step.request.headers).forEach(([k, v]) => {
            addTerminalLine('', `  ${k}: ${v}`, 'out');
          });
        }
        if (step.request.body) {
          addTerminalLine('', '  body:', 'out');
          Object.entries(step.request.body).forEach(([k, v]) => {
            addTerminalLine('', `    ${k}: ${v}`, 'out');
          });
        }
        if (step.request.params) {
          addTerminalLine('', '  query params:', 'out');
          Object.entries(step.request.params).forEach(([k, v]) => {
            addTerminalLine('', `    ${k}: ${v}`, 'out');
          });
        }
      }

      // Show response details if present
      if (step.response) {
        addTerminalLine('', '', 'in');
        addTerminalLine('', '  ── RESPONSE ─────────────────────────────────────────', 'in');
        if (step.response.status_code) {
          const sc = step.response.status_code;
          addTerminalLine('', `  HTTP ${sc}`, sc >= 400 ? 'err' : 'in');
        }
        const responseBody = step.response.body || step.response;
        if (typeof responseBody === 'object') {
          Object.entries(responseBody).forEach(([k, v]) => {
            addTerminalLine('', `  ${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`, isError ? 'err' : 'in');
          });
        } else {
          addTerminalLine('', `  ${responseBody}`, isError ? 'err' : 'in');
        }
      }
    });

    // Summary line
    addTerminalSection('── RESULT ──────────────────────────────────────────────────');
    if (data.authenticated) {
      const scopes = data.scopes.length ? data.scopes.join(', ') : 'unknown';
      const expires = data.expires_at
        ? `Expires: ${new Date(data.expires_at).toLocaleTimeString()}`
        : 'No expiry recorded';
      addTerminalLine(new Date().toLocaleTimeString(), `✓ Authenticated. Scopes: ${scopes}. ${expires}`, 'in');
      addTerminalLine('', '  Token stored in server memory only — not written to disk.', 'in');
      await pollAuthStatus(); // refresh topbar indicator
    } else {
      const errorStep = data.steps.find(s => s.status === 'error');
      const errorMsg = errorStep ? errorStep.label : 'Authentication failed';
      addTerminalLine(new Date().toLocaleTimeString(), `✗ ${errorMsg}`, 'err');
      addTerminalLine('', '  Click "Re-auth REST" to try again.', 'err');
    }

  } catch (err) {
    appendTerminalMessage(`Failed to load OAuth flow details: ${err.message}`, 'err');
  }
}

// ── Account OAuth flow → Terminal renderer ─────────────────────────────────────

async function renderAccountOAuthFlowInTerminal() {
  try {
    const res = await fetch('/auth/account-flow-status');
    if (!res.ok) return;
    const data = await res.json();

    terminalOutput.innerHTML = '';
    addTerminalSection('── OAUTH 2.0 ACCOUNT TOKEN FLOW ────────────────────────────');
    addTerminalLine(new Date().toLocaleTimeString(), 'Starting flow: REST API account token via Lucid OAuth 2.0 (authorizeAccount)', 'out');

    data.steps.forEach(step => {
      const ts = new Date().toLocaleTimeString();
      const isError = step.status === 'error';
      const isPending = step.status === 'pending';
      const icon = isError ? '✗' : isPending ? '…' : '✓';
      const type = isError ? 'err' : 'out';

      addTerminalSection(`STEP ${step.step} — ${step.label.toUpperCase()}`);
      addTerminalLine(ts, `${icon} ${step.label}`, type);
      addTerminalLine('', `  ${step.detail}`, type);

      if (step.request) {
        addTerminalLine('', '', 'out');
        addTerminalLine('', '  ── REQUEST ──────────────────────────────────────────', 'out');
        if (step.request.method) addTerminalLine('', `  ${step.request.method} ${step.request.url || ''}`, 'out');
        if (step.request.body) {
          addTerminalLine('', '  body:', 'out');
          Object.entries(step.request.body).forEach(([k, v]) => addTerminalLine('', `    ${k}: ${v}`, 'out'));
        }
        if (step.request.params) {
          addTerminalLine('', '  query params:', 'out');
          Object.entries(step.request.params).forEach(([k, v]) => addTerminalLine('', `    ${k}: ${v}`, 'out'));
        }
      }

      if (step.response) {
        addTerminalLine('', '', 'in');
        addTerminalLine('', '  ── RESPONSE ─────────────────────────────────────────', 'in');
        if (step.response.status_code) {
          const sc = step.response.status_code;
          addTerminalLine('', `  HTTP ${sc}`, sc >= 400 ? 'err' : 'in');
        }
        const responseBody = step.response.body || step.response;
        if (typeof responseBody === 'object') {
          Object.entries(responseBody).forEach(([k, v]) => {
            addTerminalLine('', `  ${k}: ${typeof v === 'object' ? JSON.stringify(v) : v}`, isError ? 'err' : 'in');
          });
        } else {
          addTerminalLine('', `  ${responseBody}`, isError ? 'err' : 'in');
        }
      }
    });
  } catch (err) {
    appendTerminalMessage(`Failed to load account OAuth flow details: ${err.message}`, 'err');
  }
}

// ── Auth Flow Modal ────────────────────────────────────────────────────────────
// Single modal reused for both user token and account token flows.
// _modalFlowType controls which flow it shows: 'user' or 'account'.

const authModalOverlay  = $('#auth-modal-overlay');
const authModalTitle    = $('#auth-modal-title');
const btnOpenLucid      = $('#btn-open-lucid');
const btnRetryAuth      = $('#btn-retry-auth');
const btnAuthClose      = $('#auth-modal-close');
const btnViewFlow       = $('#btn-view-flow');
const authErrorPanel    = $('#auth-error-panel');
const authErrorDetail   = $('#auth-error-detail');
const authSuccessPanel  = $('#auth-success-panel');
const authSuccessDetail = $('#auth-success-detail');

let _modalFlowType = 'user'; // 'user' | 'account'

function _flowStatusUrl() {
  return _modalFlowType === 'account' ? '/auth/account-flow-status' : '/auth/flow-status';
}

function _flowAuthRoute() {
  return _modalFlowType === 'account' ? '/auth/lucid-account' : '/auth/lucid';
}

function _flowTitle() {
  return _modalFlowType === 'account'
    ? 'REST API — OAuth 2.0 Account Token Flow'
    : 'REST API — OAuth 2.0 Authorization Code Flow';
}

// Open modal in "fresh" state — all steps pending, ready to launch
function openAuthModalFresh(flowType = 'user') {
  _modalFlowType = flowType;
  authModalTitle.textContent = _flowTitle();
  authErrorPanel.classList.add('hidden');
  authSuccessPanel.classList.add('hidden');
  btnRetryAuth.classList.add('hidden');
  // Reset all step pills to pending
  for (let i = 1; i <= 5; i++) {
    const el = $(`#flow-step-${i}`);
    if (!el) continue;
    el.className = 'flow-step';
    el.querySelector('.flow-step-status').textContent = '⏳';
    el.querySelector('.flow-step-label').textContent = _defaultStepLabel(i);
    el.querySelector('.flow-step-detail').textContent = _defaultStepDetail(i);
  }
  btnOpenLucid.textContent = 'Open Lucid consent screen →';
  btnOpenLucid.disabled = false;
  _modalButtonMode = 'launch';
  authModalOverlay.classList.remove('hidden');
}

// Open modal populated with the last flow result from the server
async function openAuthModalWithResults(flowType = 'user') {
  _modalFlowType = flowType;
  authModalTitle.textContent = _flowTitle();
  authModalOverlay.classList.remove('hidden');
  try {
    const res = await fetch(_flowStatusUrl());
    if (!res.ok) return;
    const data = await res.json();
    renderFlowSteps(data.steps);

    if (data.authenticated) {
      authSuccessPanel.classList.remove('hidden');
      authErrorPanel.classList.add('hidden');
      const scopes = data.scopes.length ? data.scopes.join(', ') : 'unknown';
      const expires = data.expires_at
        ? ` Expires at ${new Date(data.expires_at).toLocaleTimeString()}.` : '';
      authSuccessDetail.textContent =
        `Access token stored in server memory. Scopes granted: ${scopes}.${expires} ` +
        `Token disappears on server restart — nothing written to disk.`;
      btnOpenLucid.textContent = 'Close';
      btnOpenLucid.disabled = false;
      _modalButtonMode = 'close';
      btnRetryAuth.classList.add('hidden');
    } else if (data.steps.some(s => s.status === 'error')) {
      const errorStep = data.steps.find(s => s.status === 'error');
      authErrorPanel.classList.remove('hidden');
      authSuccessPanel.classList.add('hidden');
      $('#auth-error-label').textContent = `⚠ ${errorStep.label}`;
      authErrorDetail.textContent = errorStep.detail;
      btnRetryAuth.classList.remove('hidden');
      btnOpenLucid.textContent = 'Try again →';
      btnOpenLucid.disabled = false;
      _modalButtonMode = 'retry';
    } else {
      // No completed flow yet
      btnOpenLucid.textContent = 'Close';
      btnOpenLucid.disabled = false;
      _modalButtonMode = 'close';
    }
  } catch (_) {}
}

function closeAuthModal() {
  authModalOverlay.classList.add('hidden');
}

function _defaultStepLabel(n) {
  return ['Generate state token', 'Redirect to Lucid', 'Receive authorization code',
          'Validate state token', 'Exchange code for token'][n - 1] || `Step ${n}`;
}

function _defaultStepDetail(n) {
  return [
    'A random CSRF-protection token — stored in server memory until callback',
    "Browser goes to Lucid's consent screen with client_id, scopes, redirect_uri",
    'Lucid sends a one-time authorization code to /callback',
    'State parameter must match what was stored — prevents request forgery',
    "Server-to-server POST with client_secret — token never touches the browser",
  ][n - 1] || '';
}

function renderFlowSteps(steps) {
  steps.forEach(s => {
    const el = $(`#flow-step-${s.step}`);
    if (!el) return;
    el.classList.remove('step-ok', 'step-error', 'step-pending');
    if (s.status === 'ok')      { el.classList.add('step-ok');      el.querySelector('.flow-step-status').textContent = '✓'; }
    if (s.status === 'error')   { el.classList.add('step-error');   el.querySelector('.flow-step-status').textContent = '✗'; }
    if (s.status === 'pending') { el.classList.add('step-pending'); el.querySelector('.flow-step-status').textContent = '…'; }
    el.querySelector('.flow-step-label').textContent  = s.label;
    el.querySelector('.flow-step-detail').textContent = s.detail;
  });
}

// Single state variable for what the primary modal button does
let _modalButtonMode = 'launch'; // 'launch' | 'close' | 'retry'

function startAuthFlow(flowType = 'user') {
  // Open modal in fresh state so user sees the steps before redirect
  openAuthModalFresh(flowType);
  btnOpenLucid.disabled = true;
  btnOpenLucid.textContent = 'Redirecting to Lucid…';
  _modalButtonMode = null;

  // Navigate after a short delay so the engineer sees the modal first
  setTimeout(() => { window.location.href = _flowAuthRoute(); }, 900);
}

// Primary modal button — behaviour depends on current mode
btnOpenLucid.addEventListener('click', () => {
  if (_modalButtonMode === 'close')  { closeAuthModal(); return; }
  // On retry/launch, preserve the current flow type
  if (_modalButtonMode === 'retry')  { closeAuthModal(); startAuthFlow(_modalFlowType); return; }
  if (_modalButtonMode === 'launch') { closeAuthModal(); startAuthFlow(_modalFlowType); return; }
});

// Wire up all other buttons
btnReauth.addEventListener('click', () => startAuthFlow('user'));
btnRetryAuth.addEventListener('click', () => { closeAuthModal(); startAuthFlow(_modalFlowType); });
btnAuthClose.addEventListener('click', closeAuthModal);
btnViewFlow.addEventListener('click', () => openAuthModalWithResults('user'));
authModalOverlay.addEventListener('click', (e) => {
  if (e.target === authModalOverlay) closeAuthModal();
});

// Account token auth — opens modal then redirects
btnReauthAccount.addEventListener('click', () => startAuthFlow('account'));
btnViewAccountFlow.addEventListener('click', () => openAuthModalWithResults('account'));

// ── Sidebar navigation ─────────────────────────────────────────────────────────

function initSidebar() {
  // Surface header toggles
  $$('.surface-header').forEach(header => {
    header.addEventListener('click', () => {
      const surface = header.dataset.surface;
      const list = $(`#endpoints-${surface}`);
      const isExpanded = header.classList.contains('expanded');
      header.classList.toggle('expanded', !isExpanded);
      list.classList.toggle('open', !isExpanded);
    });
  });

  // Endpoint clicks
  $$('.endpoint-item').forEach(item => {
    item.addEventListener('click', () => {
      const key = item.dataset.endpoint;
      if (key === 'mcpPrompt') {
        showWorkspace('mcp');
      } else {
        loadEndpoint(key);
      }
      // Mark active
      $$('.endpoint-item').forEach(i => i.classList.remove('active'));
      item.classList.add('active');
    });
  });

  // Surface cards "Explore" buttons
  $$('.btn-explore').forEach(btn => {
    btn.addEventListener('click', () => {
      const surface = btn.dataset.surface;
      if (surface === 'mcp') {
        showWorkspace('mcp');
      } else {
        // Expand sidebar section and load first endpoint for that surface
        const header = $(`.surface-header[data-surface="${surface}"]`);
        const list   = $(`#endpoints-${surface}`);
        header.classList.add('expanded');
        list.classList.add('open');
        // Load first endpoint in that surface
        const firstItem = list.querySelector('.endpoint-item');
        if (firstItem) {
          firstItem.click();
        }
      }
    });
  });
}

// ── Workspace state management ─────────────────────────────────────────────────

function showWorkspace(state) {
  wsCards.classList.remove('active');
  wsEndpoint.classList.remove('active');
  wsMcp.classList.remove('active');

  if (state === 'cards')    wsCards.classList.add('active');
  if (state === 'endpoint') wsEndpoint.classList.add('active');
  if (state === 'mcp')      wsMcp.classList.add('active');
}

function loadEndpoint(key) {
  const ep = ENDPOINTS[key];
  if (!ep) return;

  currentEndpointKey = key;

  // Populate info card
  const badgeClass = `badge-${ep.method.toLowerCase()}`;
  endpointMethod.className = `method-badge ${badgeClass}`;
  endpointMethod.textContent = ep.method;
  endpointUrl.textContent = ep.urlTemplate;
  endpointDesc.textContent = ep.description;
  endpointScope.textContent = ep.scope;
  endpointDocs.href = ep.docsUrl;

  // Breadcrumb
  breadcrumbPath.textContent = `${ep.surface.toUpperCase()} API › ${ep.label}`;

  // Render param fields
  renderParamFields(ep.params);

  // Hide previous response
  responseViewer.classList.add('hidden');

  showWorkspace('endpoint');
}

// ── Parameter editor ────────────────────────────────────────────────────────────

function renderParamFields(params) {
  paramFields.innerHTML = '';

  if (params.length === 0) {
    paramFields.innerHTML = '<p style="color:var(--text-muted);font-size:12px;">No parameters required for this endpoint.</p>';
    return;
  }

  params.forEach(param => {
    const wrapper = document.createElement('div');
    wrapper.className = 'param-field';

    const label = document.createElement('label');
    label.className = 'param-label';
    label.htmlFor = `param-${param.name}`;
    // tokenSource renders as 'string' in the type badge since it IS a string field
    const displayType = param.type === 'tokenSource' ? 'string' : param.type;
    label.innerHTML = `
      ${param.label}
      ${param.required ? '<span class="param-required" title="Required">*</span>' : ''}
      <span class="param-type">${displayType}</span>
    `;

    let input;
    if (param.type === 'json') {
      input = document.createElement('textarea');
      input.className = 'param-input';
      if (param.placeholder) input.placeholder = param.placeholder;
    } else if (param.type === 'select') {
      input = document.createElement('select');
      input.className = 'param-input param-select';
      // Add a blank first option
      const blankOpt = document.createElement('option');
      blankOpt.value = '';
      blankOpt.textContent = '— select —';
      input.appendChild(blankOpt);
      (param.options || []).forEach(opt => {
        const el = document.createElement('option');
        el.value = opt.value;
        el.textContent = opt.label;
        input.appendChild(el);
      });
    } else {
      // 'string' and 'tokenSource' both render as a plain text input
      input = document.createElement('input');
      input.type = 'text';
      input.className = 'param-input';
      if (param.hint) input.placeholder = param.hint;
    }
    input.id = `param-${param.name}`;
    input.dataset.paramName = param.name;
    input.dataset.paramRequired = param.required ? 'true' : 'false';

    const hint = document.createElement('div');
    hint.className = 'param-hint';
    hint.textContent = param.hint || '';

    const errMsg = document.createElement('div');
    errMsg.className = 'param-error-msg';
    errMsg.textContent = `${param.label} is required`;

    wrapper.appendChild(label);
    wrapper.appendChild(input);

    // For tokenSource params, render a helper that lets the user populate the field
    // from the server-side stored token (tokens are never sent to the browser otherwise).
    // param.tokenField controls which field to extract: 'access_token' (default) or 'refresh_token'.
    if (param.type === 'tokenSource') {
      const useRefreshToken = param.tokenField === 'refresh_token';
      const fieldLabel = useRefreshToken ? 'refresh token' : 'access token';

      const tokenHelper = document.createElement('div');
      tokenHelper.className = 'token-source-helper';
      tokenHelper.innerHTML = `
        <span class="token-source-label">
          ${useRefreshToken
            ? 'Use the refresh token stored in server memory to populate this field:'
            : 'Tokens are stored in server memory — use the buttons below to populate this field:'}
        </span>
        <div class="token-source-buttons">
          <button class="btn-token-source" data-token-type="user" data-target-input="param-${param.name}">
            Use user ${fieldLabel}
          </button>
          <button class="btn-token-source" data-token-type="account" data-target-input="param-${param.name}">
            Use account ${fieldLabel}
          </button>
        </div>
        <div class="token-source-status" id="token-source-status-${param.name}"></div>
      `;

      // Wire up click handlers for each "Use X token" button
      tokenHelper.querySelectorAll('.btn-token-source').forEach(btn => {
        btn.addEventListener('click', async () => {
          const tokenType   = btn.dataset.tokenType;
          const targetId    = btn.dataset.targetInput;
          const statusEl    = tokenHelper.querySelector(`#token-source-status-${param.name}`);
          const targetInput = document.getElementById(targetId);

          btn.disabled = true;
          btn.textContent = 'Fetching…';
          statusEl.textContent = '';

          try {
            const res = await fetch('/auth/token-peek');
            if (!res.ok) throw new Error(`Server returned ${res.status}`);
            const data = await res.json();

            const tokenInfo = tokenType === 'account' ? data.account_token : data.user_token;
            if (!tokenInfo) {
              statusEl.className = 'token-source-status token-source-error';
              statusEl.textContent = tokenType === 'account'
                ? '⚠ No account token in memory. Click "Auth Account Token" in the topbar.'
                : '⚠ No user token in memory. Click "Auth User Token" in the topbar.';
              return;
            }

            // Choose access_token or refresh_token depending on param.tokenField
            const rawValue = useRefreshToken ? tokenInfo.refresh_token : tokenInfo.value;
            const preview  = useRefreshToken ? tokenInfo.refresh_token_preview : tokenInfo.preview;

            if (!rawValue) {
              statusEl.className = 'token-source-status token-source-error';
              statusEl.textContent = useRefreshToken
                ? `⚠ No refresh token stored for the ${tokenType} token. Lucid may not have issued one, or it hasn't been saved yet.`
                : `⚠ No access token stored for the ${tokenType} token.`;
              return;
            }

            // Populate the input field with the actual token value
            targetInput.value = rawValue;
            targetInput.classList.remove('error');

            const scopes = tokenInfo.scopes && tokenInfo.scopes.length
              ? tokenInfo.scopes.join(' ')
              : 'unknown';
            const expires = tokenInfo.expires_at
              ? `expires ${new Date(tokenInfo.expires_at).toLocaleTimeString()}`
              : 'no expiry info';
            statusEl.className = 'token-source-status token-source-ok';
            statusEl.textContent = `✓ ${tokenType === 'account' ? 'Account' : 'User'} ${fieldLabel} populated (${preview} · scopes: ${scopes} · ${expires})`;

          } catch (err) {
            statusEl.className = 'token-source-status token-source-error';
            statusEl.textContent = `⚠ Could not fetch token: ${err.message}`;
          } finally {
            btn.disabled = false;
            btn.textContent = `Use ${tokenType} ${fieldLabel}`;
          }
        });
      });

      wrapper.appendChild(tokenHelper);
    }

    if (param.hint && param.type !== 'json' && param.type !== 'tokenSource' && param.type !== 'select') wrapper.appendChild(hint);
    // errMsg always last so the .param-input.error ~ .param-error-msg selector works
    wrapper.appendChild(errMsg);
    paramFields.appendChild(wrapper);
  });
}

function collectParams() {
  const values = {};
  let valid = true;

  $$('#param-fields .param-input').forEach(input => {
    const name = input.dataset.paramName;
    const required = input.dataset.paramRequired === 'true';
    const val = input.value.trim();

    input.classList.remove('error');

    if (required && !val) {
      input.classList.add('error');
      valid = false;
    } else {
      values[name] = val;
    }
  });

  return valid ? values : null;
}

// ── Execution ──────────────────────────────────────────────────────────────────

btnExecute.addEventListener('click', async () => {
  if (!currentEndpointKey) return;

  const params = collectParams();
  if (params === null) {
    appendTerminalMessage("Can't send a request with missing required fields. Fill them in.", 'err');
    return;
  }

  const ep = ENDPOINTS[currentEndpointKey];
  await executeEndpoint(ep, params);
});

async function executeEndpoint(ep, params) {
  btnExecute.disabled = true;
  btnExecute.innerHTML = '<span class="spinner"></span>Executing...';

  const startTime = Date.now();

  try {
    const payload = {
      endpoint: currentEndpointKey,
      params,
    };

    const res = await fetch(`/api/${ep.surface}/${currentEndpointKey}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });

    const latency = Date.now() - startTime;
    const data = await res.json();

    // Update response viewer
    displayResponse(data, latency);

    // Update terminal
    renderTerminal(data);

    // Update code tab
    renderCode(data);

    // Store for on-demand narrative — don't auto-fetch to save tokens
    lastExecutionContext = data;

    // Reset the narrative tab to prompt state so user knows they can ask
    narrativeOutput.innerHTML = '<span class="terminal-placeholder">Click "Get Narrative" to have Claude narrate this request.</span>';
    btnGetNarrative.classList.remove('hidden');

  } catch (err) {
    appendTerminalMessage(`Request failed: ${err.message}`, 'err');
  } finally {
    btnExecute.disabled = false;
    btnExecute.textContent = 'Execute';
  }
}

function displayResponse(data, latency) {
  const statusCode = data.status_code || 0;

  responseStatus.textContent = statusCode;
  responseStatus.className = 'status-badge ' + (
    statusCode >= 500 ? 'status-5xx' :
    statusCode >= 400 ? 'status-4xx' :
    'status-2xx'
  );

  responseLatency.textContent = `${latency}ms`;
  responseJson.textContent = JSON.stringify(data.body, null, 2);
  responseViewer.classList.remove('hidden');
}

// ── Terminal rendering ─────────────────────────────────────────────────────────

function renderTerminal(data) {
  const req = data.request || {};
  const res = data;
  const ts  = new Date().toLocaleTimeString();

  terminalOutput.innerHTML = '';

  // Outbound request section
  addTerminalSection('OUTBOUND REQUEST');
  addTerminalLine(ts, `${req.method} ${req.url}`, 'out');

  if (req.headers) {
    Object.entries(req.headers).forEach(([k, v]) => {
      // Partially redact auth tokens
      const display = k.toLowerCase() === 'authorization'
        ? v.replace(/(Bearer\s+)(\w{6})\w+/, '$1$2••••••••')
        : v;
      addTerminalLine('', `  ${k}: ${display}`, 'out');
    });
  }

  if (req.body) {
    addTerminalLine('', `  body: ${typeof req.body === 'string' ? req.body : JSON.stringify(req.body)}`, 'out');
  }

  // Inbound response section
  addTerminalSection('INBOUND RESPONSE');
  const statusClass = (res.status_code >= 400) ? 'err' : 'in';
  addTerminalLine(ts, `HTTP ${res.status_code}`, statusClass);

  if (res.response_headers) {
    Object.entries(res.response_headers).forEach(([k, v]) => {
      addTerminalLine('', `  ${k}: ${v}`, 'in');
    });
  }

  addTerminalLine('', `  body: ${JSON.stringify(res.body, null, 0).slice(0, 200)}${JSON.stringify(res.body, null, 0).length > 200 ? '...' : ''}`, statusClass);
}

function addTerminalSection(label) {
  const div = document.createElement('div');
  div.className = 'terminal-section';
  div.innerHTML = `<div class="terminal-section-header">${label}</div>`;
  terminalOutput.appendChild(div);
}

function addTerminalLine(ts, text, type) {
  const line = document.createElement('div');
  line.className = 'terminal-line';
  // When no timestamp, render an invisible spacer that matches the ts column width
  // (using &nbsp; to prevent the element from collapsing to zero width)
  line.innerHTML = `
    ${ts ? `<span class="terminal-ts">${escapeHtml(ts)}</span>` : '<span class="terminal-ts terminal-ts-spacer">&nbsp;</span>'}
    <span class="terminal-${type}">${escapeHtml(text)}</span>
  `;
  terminalOutput.lastElementChild.appendChild(line);
}

function appendTerminalMessage(text, type = 'out') {
  if (terminalOutput.querySelector('.terminal-placeholder')) {
    terminalOutput.innerHTML = '';
  }
  const ts = new Date().toLocaleTimeString();
  const container = document.createElement('div');
  container.className = 'terminal-section';
  const line = document.createElement('div');
  line.className = 'terminal-line';
  line.innerHTML = `
    <span class="terminal-ts">${ts}</span>
    <span class="terminal-${type}">${escapeHtml(text)}</span>
  `;
  container.appendChild(line);
  terminalOutput.appendChild(container);
}

// ── Code tab rendering ─────────────────────────────────────────────────────────

function renderCode(data) {
  const req = data.request || {};
  curlOutput.textContent  = data.curl_command  || generateCurl(req);
  pythonOutput.textContent = data.python_snippet || generatePython(req);
}

function generateCurl(req) {
  if (!req.url) return 'No request data available.';
  const method = req.method || 'GET';
  const headers = Object.entries(req.headers || {})
    .map(([k, v]) => {
      const display = k.toLowerCase() === 'authorization'
        ? v.replace(/(Bearer\s+)(\w{6})\w+/, '$1$2••••••••')
        : v;
      return `-H '${k}: ${display}'`;
    })
    .join(' \\\n     ');
  const body = req.body ? `-d '${typeof req.body === 'string' ? req.body : JSON.stringify(req.body)}' \\` : '';
  return `curl -X ${method} '${req.url}' \\\n     ${headers}${body ? '\n     ' + body : ''}`;
}

function generatePython(req) {
  if (!req.url) return 'No request data available.';
  const method = (req.method || 'GET').toLowerCase();
  const headers = JSON.stringify(req.headers || {}, null, 2).replace(/^/gm, '    ').trimStart();
  const bodyLine = req.body
    ? `\njson = ${JSON.stringify(typeof req.body === 'string' ? JSON.parse(req.body) : req.body, null, 2)}`
    : '';
  const bodyArg = req.body ? ', json=json' : '';
  return `import requests\n\nheaders = ${headers}${bodyLine}\n\nresponse = requests.${method}(\n    '${req.url}',\n    headers=headers${bodyArg}\n)\n\nprint(response.status_code)\nprint(response.json())`;
}

// ── Claude Narrative ───────────────────────────────────────────────────────────

async function fetchNarrative(executionData) {
  narrativeOutput.innerHTML = '<span class="spinner"></span> Generating narrative...';

  try {
    const res = await fetch('/ai/narrative', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ execution_data: executionData }),
    });

    if (!res.ok) throw new Error(`${res.status}`);
    const data = await res.json();
    renderNarrative(data.narrative);
  } catch (err) {
    narrativeOutput.innerHTML = `<span style="color:var(--error-red)">Narrative unavailable: ${escapeHtml(err.message)}</span>`;
  }
}

function renderNarrative(text) {
  // Parse four-beat structure: lines starting with ✦ BEAT or THE BEAT or WHAT THIS MEANS
  narrativeOutput.innerHTML = '';

  const beats = text.split(/(?=✦\s|THE REQUEST|THE RESPONSE|WHAT THIS MEANS)/);
  beats.forEach(beat => {
    if (!beat.trim()) return;

    const div = document.createElement('div');
    div.className = 'narrative-beat';

    // Find label (first line)
    const lines = beat.trim().split('\n');
    const labelLine = lines[0];
    const body = lines.slice(1).join('\n').trim();

    const labelEl = document.createElement('div');
    labelEl.className = 'narrative-beat-label';
    labelEl.textContent = labelLine;

    const textEl = document.createElement('div');
    textEl.className = 'narrative-beat-text';
    textEl.textContent = body;

    div.appendChild(labelEl);
    div.appendChild(textEl);
    narrativeOutput.appendChild(div);
  });
}

// Get Narrative button — only fires Claude when explicitly clicked
btnGetNarrative.addEventListener('click', async () => {
  if (!lastExecutionContext) return;
  btnGetNarrative.classList.add('hidden');
  switchTab('narrative');
  await fetchNarrative(lastExecutionContext);
});

// Follow-up questions
btnFollowup.addEventListener('click', submitFollowup);
followupInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') submitFollowup();
});

async function submitFollowup() {
  const question = followupInput.value.trim();
  if (!question) return;

  followupInput.value = '';
  btnFollowup.disabled = true;

  const responseEl = document.createElement('div');
  responseEl.className = 'narrative-followup-response';
  responseEl.innerHTML = `<strong>Q: ${escapeHtml(question)}</strong><br><span class="spinner"></span> Thinking...`;
  narrativeOutput.appendChild(responseEl);

  try {
    const res = await fetch('/ai/followup', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, context: lastExecutionContext }),
    });

    if (!res.ok) throw new Error(`${res.status}`);
    const data = await res.json();
    responseEl.innerHTML = `<strong>Q: ${escapeHtml(question)}</strong><br>${escapeHtml(data.answer)}`;
  } catch (err) {
    responseEl.innerHTML = `<strong>Q: ${escapeHtml(question)}</strong><br><span style="color:var(--error-red)">Error: ${escapeHtml(err.message)}</span>`;
  } finally {
    btnFollowup.disabled = false;
    narrativeOutput.scrollTop = narrativeOutput.scrollHeight;
  }
}

// ── MCP workspace ──────────────────────────────────────────────────────────────

btnMcpSubmit.addEventListener('click', async () => {
  const prompt = mcpPromptInput.value.trim();
  if (!prompt) return;

  btnMcpSubmit.disabled = true;
  btnMcpSubmit.innerHTML = '<span class="spinner"></span>Submitting...';

  try {
    const res = await fetch('/api/mcp/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });

    const data = await res.json();
    mcpResponseContent.textContent = JSON.stringify(data, null, 2);
    mcpResponseViewer.classList.remove('hidden');

    renderTerminal(data);
    switchTab('narrative');
    await fetchNarrative(data);
    lastExecutionContext = data;
  } catch (err) {
    appendTerminalMessage(`MCP request failed: ${err.message}`, 'err');
  } finally {
    btnMcpSubmit.disabled = false;
    btnMcpSubmit.textContent = 'Submit';
  }
});

// ── Notepad ────────────────────────────────────────────────────────────────────

btnAskClaude.addEventListener('click', async () => {
  const content = notepad.value.trim();
  if (!content) return;

  btnAskClaude.disabled = true;
  switchTab('narrative');
  narrativeOutput.innerHTML = '<span class="spinner"></span> Reading your notepad...';

  try {
    const res = await fetch('/ai/notepad', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    });

    const data = await res.json();
    narrativeOutput.innerHTML = `<div class="narrative-beat-text">${escapeHtml(data.response)}</div>`;
  } catch (err) {
    narrativeOutput.innerHTML = `<span style="color:var(--error-red)">Error: ${escapeHtml(err.message)}</span>`;
  } finally {
    btnAskClaude.disabled = false;
  }
});

// ── Bottom panel tabs ──────────────────────────────────────────────────────────

panelTabs.forEach(tab => {
  tab.addEventListener('click', () => switchTab(tab.dataset.tab));
});

function switchTab(name) {
  panelTabs.forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  [tabTerminal, tabCode, tabNarrative].forEach(pane => {
    pane.classList.toggle('active', pane.id === `tab-${name}`);
  });
}

// ── Copy buttons ───────────────────────────────────────────────────────────────

$$('.btn-copy').forEach(btn => {
  btn.addEventListener('click', () => {
    const target = document.getElementById(btn.dataset.target);
    if (!target) return;
    navigator.clipboard.writeText(target.textContent).then(() => {
      btn.textContent = 'Copied!';
      btn.classList.add('copied');
      setTimeout(() => {
        btn.textContent = 'Copy';
        btn.classList.remove('copied');
      }, 2000);
    });
  });
});

// ── Nav buttons ────────────────────────────────────────────────────────────────

btnBack.addEventListener('click', () => {
  showWorkspace('cards');
  currentEndpointKey = null;
  $$('.endpoint-item').forEach(i => i.classList.remove('active'));
});

btnBackMcp.addEventListener('click', () => {
  showWorkspace('cards');
  $$('.endpoint-item').forEach(i => i.classList.remove('active'));
});

// (btnReauth handler is defined above in the Auth Flow Modal section)

// ── Utilities ──────────────────────────────────────────────────────────────────

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// ── Init ───────────────────────────────────────────────────────────────────────

function init() {
  initSidebar();
  pollAuthStatus();
  setInterval(pollAuthStatus, 15000); // Poll every 15s to keep status fresh
  // handleOAuthRedirect last — it may open the modal which reads DOM state
  handleOAuthRedirect();
}

document.addEventListener('DOMContentLoaded', init);
