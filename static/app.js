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

  // ── Accounts ────────────────────────────────────────────────────────────────
  getAccountInfo: {
    surface: 'rest',
    method: 'GET',
    label: 'getAccountInfo',
    urlTemplate: 'https://api.lucid.co/accounts/me',
    description: 'Returns basic account information for the authenticated account (name, ID, plan type).',
    scope: 'account.info',
    docsUrl: 'https://developer.lucid.co/reference/getaccountinformation',
    params: [],
  },

  // ── Documents ────────────────────────────────────────────────────────────────
  searchAccountDocuments: {
    surface: 'rest',
    method: 'POST',
    label: 'searchAccountDocuments',
    urlTemplate: 'https://api.lucid.co/accounts/me/documents/search',
    description: 'Search all documents in the account (Enterprise Shield only). Requires an account token with admin document scope.',
    scope: 'lucidchart.document.content:admin.readonly',
    docsUrl: 'https://developer.lucid.co/reference/searchaccountdocuments',
    params: [
      {
        name: 'body',
        label: 'Request Body (JSON)',
        type: 'json',
        required: false,
        hint: 'Optional filter criteria. Leave blank to return all account documents.',
        placeholder: '{\n  "keywords": "my diagram"\n}',
      },
    ],
  },
  searchDocuments: {
    surface: 'rest',
    method: 'POST',
    label: 'searchDocuments',
    urlTemplate: 'https://api.lucid.co/documents/search',
    description: "Search documents accessible to the authenticated user. When 'keywords' is provided, results are sorted by relevance.",
    scope: 'lucidchart.document.content:readonly',
    docsUrl: 'https://developer.lucid.co/reference/searchdocuments',
    params: [
      {
        name: 'body',
        label: 'Request Body (JSON)',
        type: 'json',
        required: false,
        hint: 'Optional filter criteria. Leave blank to return all accessible documents.',
        placeholder: '{\n  "keywords": "architecture diagram"\n}',
      },
    ],
  },
  createDocument: {
    surface: 'rest',
    method: 'POST',
    label: 'createDocument',
    urlTemplate: 'https://api.lucid.co/documents',
    description: "Create a new Lucidchart or Lucidspark document. Use 'product' to specify which app.",
    scope: 'lucidchart.document.content',
    docsUrl: 'https://developer.lucid.co/reference/createorcopyorimportdocument',
    params: [
      {
        name: 'body',
        label: 'Request Body (JSON)',
        type: 'json',
        required: true,
        hint: 'Must include title and product. Optionally include parent folder ID.',
        placeholder: '{\n  "title": "My New Diagram",\n  "product": "lucidchart"\n}',
      },
    ],
  },
  importStandardImport: {
    surface: 'rest',
    method: 'POST',
    label: 'importStandardImport',
    urlTemplate: 'https://api.lucid.co/documents',
    description: 'Import a Lucidchart/Lucidspark diagram from Standard Import JSON. This app packages your JSON as document.json inside an import.lucid zip, then uploads it via multipart.',
    scope: 'lucidchart.document.content',
    docsUrl: 'https://developer.lucid.co/reference/createorcopyorimportdocument',
    params: [
      {
        name: 'product',
        label: 'Product',
        type: 'select',
        required: true,
        hint: 'Target Lucid product for the new document',
        options: [
          { value: 'lucidchart', label: 'lucidchart' },
          { value: 'lucidspark', label: 'lucidspark' },
        ],
      },
      {
        name: 'title',
        label: 'Title',
        type: 'string',
        required: false,
        hint: 'Optional document title',
      },
      {
        name: 'parent',
        label: 'Parent folder ID',
        type: 'string',
        required: false,
        hint: 'Optional parent folder ID',
      },
      {
        name: 'body',
        label: 'Standard Import JSON (document.json)',
        type: 'json',
        required: true,
        hint: 'Paste Standard Import JSON (version/pages/shapes/lines/etc).',
        placeholder: '{\n  "version": 1,\n  "pages": [\n    {\n      "id": "page-1",\n      "title": "Generated Diagram",\n      "shapes": []\n    }\n  ]\n}',
      },
    ],
  },
  getDocument: {
    surface: 'rest',
    method: 'GET',
    label: 'getDocument',
    urlTemplate: 'https://api.lucid.co/documents/{documentId}',
    description: 'Get metadata for a document by ID — title, owner, product, timestamps, and export links.',
    scope: 'lucidchart.document.content:readonly',
    docsUrl: 'https://developer.lucid.co/reference/getorexportdocument',
    params: [
      { name: 'documentId', label: 'Document ID', type: 'string', required: true, hint: 'The Lucid document identifier (e.g. a1b2c3d4-...)' },
    ],
  },
  getDocumentContents: {
    surface: 'rest',
    method: 'GET',
    label: 'getDocumentContents',
    urlTemplate: 'https://api.lucid.co/documents/{documentId}/contents',
    description: 'Retrieve the full structured content (pages, shapes, connectors) of a document.',
    scope: 'lucidchart.document.content:readonly',
    docsUrl: 'https://developer.lucid.co/reference/getdocumentcontent',
    params: [
      { name: 'documentId', label: 'Document ID', type: 'string', required: true, hint: 'The Lucid document identifier' },
    ],
  },
  trashDocument: {
    surface: 'rest',
    method: 'POST',
    label: 'trashDocument',
    urlTemplate: 'https://api.lucid.co/documents/{documentId}/trash',
    description: "Move a document to the authenticated user's trash. Shared documents remain accessible to others.",
    scope: 'lucidchart.document.content',
    docsUrl: 'https://developer.lucid.co/reference/trashdocument',
    params: [
      { name: 'documentId', label: 'Document ID', type: 'string', required: true, hint: 'The Lucid document identifier' },
    ],
  },

  // ── Folders ──────────────────────────────────────────────────────────────────
  getFolder: {
    surface: 'rest',
    method: 'GET',
    label: 'getFolder',
    urlTemplate: 'https://api.lucid.co/folders/{folderId}',
    description: 'Get metadata for a folder by ID — name, owner, parent folder, and timestamps.',
    scope: 'folder:readonly',
    docsUrl: 'https://developer.lucid.co/reference/getfolder',
    params: [
      { name: 'folderId', label: 'Folder ID', type: 'string', required: true, hint: 'The numeric folder identifier (e.g. 123456)' },
    ],
  },
  createFolder: {
    surface: 'rest',
    method: 'POST',
    label: 'createFolder',
    urlTemplate: 'https://api.lucid.co/folders',
    description: 'Create a new folder. Optionally specify a parent folder ID to nest it.',
    scope: 'folder',
    docsUrl: 'https://developer.lucid.co/reference/createfolder',
    params: [
      {
        name: 'body',
        label: 'Request Body (JSON)',
        type: 'json',
        required: true,
        hint: 'Must include name. Optionally include parentId.',
        placeholder: '{\n  "name": "My New Folder"\n}',
      },
    ],
  },
  updateFolder: {
    surface: 'rest',
    method: 'PATCH',
    label: 'updateFolder',
    urlTemplate: 'https://api.lucid.co/folders/{folderId}',
    description: 'Update a folder — rename it or move it to a new parent. Moving preserves all contents.',
    scope: 'folder',
    docsUrl: 'https://developer.lucid.co/reference/updatefolder',
    params: [
      { name: 'folderId', label: 'Folder ID', type: 'string', required: true, hint: 'The numeric folder identifier' },
      {
        name: 'body',
        label: 'Request Body (JSON)',
        type: 'json',
        required: true,
        hint: 'Fields to update: name and/or parent (numeric folder ID).',
        placeholder: '{\n  "name": "Renamed Folder"\n}',
      },
    ],
  },
  trashFolder: {
    surface: 'rest',
    method: 'POST',
    label: 'trashFolder',
    urlTemplate: 'https://api.lucid.co/folders/{folderId}/trash',
    description: 'Move a folder and all of its contents to the trash.',
    scope: 'folder',
    docsUrl: 'https://developer.lucid.co/reference/trashfolder',
    params: [
      { name: 'folderId', label: 'Folder ID', type: 'string', required: true, hint: 'The numeric folder identifier' },
    ],
  },
  restoreFolder: {
    surface: 'rest',
    method: 'POST',
    label: 'restoreFolder',
    urlTemplate: 'https://api.lucid.co/folders/{folderId}/restore',
    description: 'Restore a trashed folder and all its contents to their original location.',
    scope: 'folder',
    docsUrl: 'https://developer.lucid.co/reference/restorefolder',
    params: [
      { name: 'folderId', label: 'Folder ID', type: 'string', required: true, hint: 'The numeric folder identifier' },
    ],
  },
  listFolderContents: {
    surface: 'rest',
    method: 'GET',
    label: 'listFolderContents',
    urlTemplate: 'https://api.lucid.co/folders/{folderId}/contents',
    description: 'List all documents and sub-folders directly inside a given folder.',
    scope: 'folder:readonly',
    docsUrl: 'https://developer.lucid.co/reference/listfoldercontents',
    params: [
      { name: 'folderId', label: 'Folder ID', type: 'string', required: true, hint: 'The numeric folder identifier' },
    ],
  },
  listRootFolderContents: {
    surface: 'rest',
    method: 'GET',
    label: 'listRootFolderContents',
    urlTemplate: 'https://api.lucid.co/folders/root/contents',
    description: "List documents and folders in the authenticated user's root folder. No ID needed.",
    scope: 'folder:readonly',
    docsUrl: 'https://developer.lucid.co/reference/listrootfoldercontents',
    params: [],
  },

  // OAuth Token Management
  refreshAccessToken: {
    surface: 'rest',
    method: 'POST',
    label: 'refreshAccessToken',
    urlTemplate: 'https://api.lucid.co/oauth2/token',
    description: 'Create a new access token from an authorization code, or refresh an existing token using a refresh token. client_id and client_secret are injected by this app — never exposed to the browser. On success, the new token is automatically saved to this app\'s memory.',
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

const SI_TEMPLATE_LIBRARY = {
  flowchart: {
    label: 'Flowchart Starter',
    document: {
      version: 1,
      pages: [
        {
          id: 'page-flow',
          title: 'API Request Flow',
          shapes: [
            { id: 'start', type: 'process', text: '1) User action in browser', boundingBox: { x: 80, y: 90, w: 220, h: 64 } },
            { id: 'app', type: 'process', text: '2) Lucid API Explorer server', boundingBox: { x: 360, y: 90, w: 240, h: 64 } },
            { id: 'lucid', type: 'process', text: '3) Lucid API surface', boundingBox: { x: 660, y: 90, w: 200, h: 64 } },
            { id: 'resp', type: 'process', text: '4) Response + narrative shown', boundingBox: { x: 360, y: 230, w: 260, h: 64 } },
            { id: 'hint-a', type: 'process', text: 'Flow: 1 -> 2 -> 3 -> 4', boundingBox: { x: 360, y: 320, w: 260, h: 46 } },
            { id: 'hint-b', type: 'process', text: 'Iterate: 4 -> 1', boundingBox: { x: 80, y: 230, w: 220, h: 46 } },
          ],
          lines: [
            { id: 'f1', source: 'start', target: 'app' },
            { id: 'f2', source: 'app', target: 'lucid' },
            { id: 'f3', source: 'lucid', target: 'resp' },
            { id: 'f4', source: 'resp', target: 'start' },
          ],
        },
      ],
    },
  },
  orgchart: {
    label: 'Org Chart Starter',
    document: {
      version: 1,
      pages: [
        {
          id: 'page-org',
          title: 'App Components',
          shapes: [
            { id: 'root', type: 'process', text: 'Lucid API Explorer', boundingBox: { x: 350, y: 40, w: 220, h: 62 } },
            { id: 'tier1', type: 'process', text: 'Tier 1: API Surfaces', boundingBox: { x: 345, y: 140, w: 230, h: 56 } },
            { id: 'rest', type: 'process', text: 'Tier 2: REST', boundingBox: { x: 120, y: 250, w: 170, h: 52 } },
            { id: 'scim', type: 'process', text: 'Tier 2: SCIM', boundingBox: { x: 380, y: 250, w: 170, h: 52 } },
            { id: 'mcp', type: 'process', text: 'Tier 2: MCP', boundingBox: { x: 640, y: 250, w: 170, h: 52 } },
            { id: 'panel', type: 'process', text: 'Tier 3: Terminal / Code / Narrative', boundingBox: { x: 300, y: 360, w: 340, h: 56 } },
            { id: 'org-note', type: 'process', text: 'Hierarchy reads top-down by tiers', boundingBox: { x: 300, y: 440, w: 340, h: 44 } },
          ],
          lines: [
            { id: 'o1', source: 'root', target: 'tier1' },
            { id: 'o2', source: 'tier1', target: 'rest' },
            { id: 'o3', source: 'tier1', target: 'scim' },
            { id: 'o4', source: 'tier1', target: 'mcp' },
            { id: 'o5', source: 'rest', target: 'panel' },
            { id: 'o6', source: 'scim', target: 'panel' },
            { id: 'o7', source: 'mcp', target: 'panel' },
          ],
        },
      ],
    },
  },
  swimlane: {
    label: 'Swimlane Starter',
    document: {
      version: 1,
      pages: [
        {
          id: 'page-lane',
          title: 'OAuth + DCR Swimlane',
          shapes: [
            { id: 'lane-a', type: 'process', text: 'BROWSER LANE', boundingBox: { x: 40, y: 40, w: 1040, h: 110 } },
            { id: 'lane-b', type: 'process', text: 'APP SERVER LANE', boundingBox: { x: 40, y: 190, w: 1040, h: 120 } },
            { id: 'lane-c', type: 'process', text: 'LUCID LANE', boundingBox: { x: 40, y: 350, w: 1040, h: 120 } },
            { id: 'b1', type: 'process', text: '1) Browser: Click Connect MCP', boundingBox: { x: 90, y: 72, w: 280, h: 50 } },
            { id: 's1', type: 'process', text: '2) Server: POST /oauth/register', boundingBox: { x: 420, y: 225, w: 280, h: 52 } },
            { id: 'l1', type: 'process', text: '3) Lucid: Consent + auth', boundingBox: { x: 760, y: 385, w: 260, h: 52 } },
            { id: 's2', type: 'process', text: '4) Server: code -> token exchange', boundingBox: { x: 760, y: 225, w: 280, h: 52 } },
            { id: 's3', type: 'process', text: '5) Server: POST /mcp prompt', boundingBox: { x: 90, y: 225, w: 280, h: 52 } },
            { id: 'swim-note', type: 'process', text: 'Sequence: Browser -> Server -> Lucid -> Server -> Server', boundingBox: { x: 300, y: 500, w: 520, h: 44 } },
          ],
          lines: [
            { id: 'sl1', source: 'b1', target: 's1' },
            { id: 'sl2', source: 's1', target: 'l1' },
            { id: 'sl3', source: 'l1', target: 's2' },
            { id: 'sl4', source: 's2', target: 's3' },
          ],
        },
      ],
    },
  },
};

const SI_SESSION_LOG_LIMIT = 20;
const siSessionEvents = [];

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
const scopeSummaryTrigger = $('#scope-summary-trigger');
const scopeSummaryPanel = $('#scope-summary-panel');
const scopeSummaryUserPill = $('#scope-summary-user');
const scopeSummaryAccountPill = $('#scope-summary-account');
const scopeSummaryUserList = $('#scope-summary-user-list');
const scopeSummaryAccountList = $('#scope-summary-account-list');
const btnReauth         = $('#btn-reauth');
const btnReauthAccount  = $('#btn-reauth-account');

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
const mcpStructuredResults = $('#mcp-structured-results');
const mcpRawControls = $('#mcp-raw-controls');
const btnMcpRawToggle = $('#btn-mcp-raw-toggle');
const mcpAuthBanner     = $('#mcp-auth-banner');

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
    const data = sanitizeExecutionData(await res.json());
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

  // Toggle MCP banner between disconnected/connected states.
  // We NEVER rebuild innerHTML — both state divs are permanently in the DOM.
  // JS only flips .hidden and .auth-banner-connected.
  if (mcpAuthBanner) {
    mcpAuthBanner.classList.toggle('auth-banner-connected', mcpOk);
    $('#mcp-banner-disconnected').classList.toggle('hidden', mcpOk);
    $('#mcp-banner-connected').classList.toggle('hidden', !mcpOk);
  }
  // Enable/disable MCP submit based on auth state
  if (btnMcpSubmit) {
    btnMcpSubmit.disabled = !mcpOk;
    btnMcpSubmit.title = mcpOk ? '' : 'Connect MCP first';
  }

  renderScopeSummary(status);
}

function renderScopeSummary(status) {
  const userAuthed = !!(status.rest && status.rest.authenticated);
  const accountAuthed = !!(status.rest_account && status.rest_account.authenticated);
  const userScopes = (status.rest && Array.isArray(status.rest.scopes)) ? status.rest.scopes : [];
  const accountScopes = (status.rest_account && Array.isArray(status.rest_account.scopes)) ? status.rest_account.scopes : [];

  scopeSummaryUserPill.textContent = userAuthed ? `U ✓` : 'U -';
  scopeSummaryAccountPill.textContent = accountAuthed ? `A ✓` : 'A -';

  scopeSummaryUserPill.classList.toggle('scope-summary-pill-active', userAuthed);
  scopeSummaryUserPill.classList.toggle('scope-summary-pill-inactive', !userAuthed);
  scopeSummaryAccountPill.classList.toggle('scope-summary-pill-active', accountAuthed);
  scopeSummaryAccountPill.classList.toggle('scope-summary-pill-inactive', !accountAuthed);

  scopeSummaryUserPill.title = userAuthed
    ? `User token active (${userScopes.length} scopes)`
    : 'User token not authenticated';
  scopeSummaryAccountPill.title = accountAuthed
    ? `Account token active (${accountScopes.length} scopes)`
    : 'Account token not authenticated';

  scopeSummaryUserList.innerHTML = userScopes.length
    ? userScopes.map(s => `<span class="scope-chip">${escapeHtml(s)}</span>`).join('')
    : '<span class="scope-summary-empty">No user token scopes authorized</span>';

  scopeSummaryAccountList.innerHTML = accountScopes.length
    ? accountScopes.map(s => `<span class="scope-chip scope-chip-account">${escapeHtml(s)}</span>`).join('')
    : '<span class="scope-summary-empty">No account token scopes authorized</span>';
}

// Check for auth result in URL on page load (redirected back from OAuth)
async function handleOAuthRedirect() {
  const params = new URLSearchParams(window.location.search);
  const success        = params.get('auth_success');
  const error          = params.get('auth_error');
  const accountSuccess = params.get('account_auth_success');
  const accountError   = params.get('account_auth_error');
  const mcpSuccess     = params.get('mcp_auth_success');
  const mcpError       = params.get('mcp_auth_error');

  // Always clean the URL immediately
  window.history.replaceState({}, '', '/');

  if (success || error) {
    switchTab('terminal');
    await renderOAuthFlowInTerminal();
    btnViewFlows.classList.remove('hidden');
    await openAuthModalViewer('user');
  }

  if (accountSuccess || accountError) {
    switchTab('terminal');
    await renderAccountOAuthFlowInTerminal();
    btnViewFlows.classList.remove('hidden');
    await openAuthModalViewer('account');
  }

  if (mcpSuccess || mcpError) {
    // Navigate to MCP workspace and show result in terminal
    showWorkspace('mcp');
    switchTab('terminal');
    terminalOutput.innerHTML = '';
    if (mcpSuccess) {
      const ts = () => new Date().toLocaleTimeString();
      addTerminalSection('── MCP: OAuth 2.0 + Dynamic Client Registration ─────────────');
      addTerminalLine(ts(), '① POST /oauth/register → client_id + client_secret issued', 'ok');
      addTerminalLine('',   '   No Developer Portal setup required — server registered itself automatically', 'out');
      addTerminalLine(ts(), '② Authorization URL built with PKCE code_challenge', 'ok');
      addTerminalLine(ts(), '③ Browser redirected → user approved on Lucid consent screen', 'ok');
      addTerminalLine(ts(), '④ /mcp/callback received ?code= — CSRF state validated', 'ok');
      addTerminalLine(ts(), '⑤ POST /oauth2/token — server exchanged code + verifier for access token', 'ok');
      addTerminalLine('',   '   Token held in this app\'s memory only. Session active. ✓', 'ok');
    } else {
      addTerminalSection('── MCP AUTH ERROR ───────────────────────────────────────────');
      addTerminalLine(new Date().toLocaleTimeString(), `✗ MCP auth failed: ${mcpError}`, 'err');
      addTerminalLine('', '  Try connecting again via the "Connect MCP →" button.', 'out');
    }
    // Refresh auth status so the banner updates
    await pollAuthStatus();
  }
}

// ── OAuth flow → Terminal renderer ────────────────────────────────────────────
// After the OAuth round-trip completes, fetch the full step log from the server
// and render it as a rich educational timeline in the Terminal tab.

async function renderOAuthFlowInTerminal() {
  try {
    const res = await fetch('/auth/flow-status');
    if (!res.ok) return;
    const data = sanitizeExecutionData(await res.json());

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
      addTerminalLine('', '  Token held in this app\'s memory — not written to disk.', 'in');
      await pollAuthStatus(); // refresh topbar indicator
    } else {
      const errorStep = data.steps.find(s => s.status === 'error');
      const errorMsg = errorStep ? errorStep.label : 'Authentication failed';
      addTerminalLine(new Date().toLocaleTimeString(), `✗ ${errorMsg}`, 'err');
      addTerminalLine('', '  Use the auth buttons in the topbar to try again.', 'err');
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
    const data = sanitizeExecutionData(await res.json());

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

// ── Auth Flow Modal — Step-Through Explorer ───────────────────────────────────
//
// Single modal reused for both user token and account token flows.
// _modalFlowType controls which flow it shows: 'user' or 'account'.
//
// The diagram shows three actors: Browser | Your Server | Lucid
// Each step animates a labelled "packet" travelling between the relevant pair.
// Steps 1 & 4 are "internal" (server-only) — they pulse the server actor.
// Step 5 animates a two-part exchange: server→Lucid then Lucid→server.
//
// Real payload data (from /auth/flow-status) is shown in a collapsible panel
// below the diagram. Step 2's auth URL is rendered with colour-annotated params.

const authModalOverlay  = $('#auth-modal-overlay');
const authModalTitle    = $('#auth-modal-title');
const btnOpenLucid      = $('#btn-open-lucid');
const btnRetryAuth      = $('#btn-retry-auth');
const btnAuthClose      = $('#auth-modal-close');
const btnViewFlows      = $('#btn-view-flows');   // single unified button
const authErrorPanel    = $('#auth-error-panel');
const authErrorDetail   = $('#auth-error-detail');
const authSuccessPanel  = $('#auth-success-panel');
const authSuccessDetail = $('#auth-success-detail');

// Keep these const refs alive (used for show/hide logic elsewhere in file)
const btnViewFlow        = btnViewFlows; // alias — code still references btnViewFlow
const btnViewAccountFlow = btnViewFlows; // alias

let _modalFlowType  = 'user'; // 'user' | 'account' — which tab is active
let _modalButtonMode = 'launch'; // 'launch' | 'close' | 'retry'

// Per-flow cached data — so switching tabs doesn't re-fetch
const _flowCache = { user: null, account: null };

// ── Diagram state ──────────────────────────────────────────────────────────────
let _diagramSteps   = [];  // step objects from /auth/flow-status
let _diagramCurrent = 0;   // 0-indexed current step
let _diagAnimTimer  = null; // active animation timeout — cleared on nav

// ── Step config table ──────────────────────────────────────────────────────────
// Maps each step index (0-based) to: which actors are involved, which arrow
// track to use, which direction the packet travels, and what colour to use.
//
// track: 1 = Browser↔Server lane, 2 = Server↔Lucid lane
// dir:   'right' = left→right (toward Lucid), 'left' = right→left, 'internal' = no packet
const FLOW_STEP_CONFIG = [
  // Step 1 — server generates CSRF state token (internal)
  { dir: 'internal', actor: 'server', track: null,
    defaultLabel:  'State token generated',
    defaultDetail: 'A cryptographically random value stored in this app\'s memory to prevent CSRF attacks. When the callback arrives, this app checks the returned state matches what it stored.' },
  // Step 2 — server builds auth URL and 302-redirects browser toward Lucid
  { dir: 'left', track: 1, from: 'server', to: 'browser', packetClass: 'packet-redirect',
    defaultLabel:  'Browser redirected to Lucid',
    defaultDetail: "Your server builds the authorization URL and returns a 302 redirect. Your browser follows it to Lucid's consent screen." },
  // Step 3 — Lucid redirects browser back with code; browser delivers it to server
  { dir: 'left', track: 2, from: 'lucid', to: 'server', packetClass: 'packet-code',
    defaultLabel:  'Authorization code received',
    defaultDetail: 'After consent, Lucid sends a one-time authorization code to /callback. This code is short-lived (≈60s) and single-use.' },
  // Step 4 — server validates state param (internal)
  { dir: 'internal', actor: 'server', track: null,
    defaultLabel:  'State token validated',
    defaultDetail: 'The state param Lucid echoed back is compared to what was stored. A mismatch means the redirect was forged — CSRF blocked.' },
  // Step 5 — server exchanges code for token with Lucid (two-phase: out then back)
  { dir: 'right', track: 2, from: 'server', to: 'lucid', packetClass: 'packet-token',
    defaultLabel:  'Token exchange',
    defaultDetail: 'Server-to-server POST to Lucid\'s token endpoint. The client_secret travels here — it never touches the browser. Lucid returns an access token.' },
];

// ── DOM refs (diagram elements) ────────────────────────────────────────────────
// These are grabbed lazily inside initFlowDiagram() because they only exist
// after the modal HTML is in the DOM.

let _actorBrowser, _actorServer, _actorLucid;
let _packet1, _packet2;
let _btnPrev, _btnNext;
let _counterEl;
let _calloutEl, _calloutBadge, _calloutTitle, _calloutDetail;
let _payloadToggleBtn, _payloadEl, _payloadRequest, _payloadResponse;
let _payloadOpen = false;

function _grabDiagramRefs() {
  _actorBrowser  = $('#actor-browser');
  _actorServer   = $('#actor-server');
  _actorLucid    = $('#actor-lucid');
  _packet1       = $('#flow-packet-1');
  _packet2       = $('#flow-packet-2');
  _btnPrev       = $('#btn-flow-prev');
  _btnNext       = $('#btn-flow-next');
  _counterEl     = $('#flow-step-counter');
  _calloutEl     = $('#flow-callout');
  _calloutBadge  = $('#flow-callout-step-badge');
  _calloutTitle  = $('#flow-callout-title');
  _calloutDetail = $('#flow-callout-detail');
  _payloadToggleBtn = $('#btn-payload-toggle');
  _payloadEl        = $('#flow-payload');
  _payloadRequest   = $('#flow-payload-request');
  _payloadResponse  = $('#flow-payload-response');
}

// ── Init diagram ───────────────────────────────────────────────────────────────
// Called every time the modal opens, before renderStep().

function initFlowDiagram(steps) {
  _grabDiagramRefs();
  _diagramSteps   = steps || [];
  _diagramCurrent = 0;
  _payloadOpen    = false;

  // Wire nav buttons (remove old listeners by cloning)
  const newPrev = _btnPrev.cloneNode(true);
  const newNext = _btnNext.cloneNode(true);
  _btnPrev.replaceWith(newPrev);
  _btnNext.replaceWith(newNext);
  _btnPrev = newPrev;
  _btnNext = newNext;
  _btnPrev.addEventListener('click', _retreatStep);
  _btnNext.addEventListener('click', _advanceStep);

  // Wire payload toggle
  const newToggle = _payloadToggleBtn.cloneNode(true);
  _payloadToggleBtn.replaceWith(newToggle);
  _payloadToggleBtn = newToggle;
  _payloadToggleBtn.addEventListener('click', _togglePayload);

  // Reset all actors
  [_actorBrowser, _actorServer, _actorLucid].forEach(a => {
    a.classList.remove('actor-active', 'actor-arrived', 'actor-pulse');
  });

  // Reset both packets
  [_packet1, _packet2].forEach(p => {
    p.className = 'flow-packet';
    p.textContent = '';
  });

  // Collapse payload
  _payloadEl.classList.add('hidden');
  _payloadToggleBtn.textContent = 'Show payload ▾';

  renderStep(0);
}

// ── Step renderer ──────────────────────────────────────────────────────────────

function renderStep(idx) {
  _diagramCurrent = idx;
  const total = FLOW_STEP_CONFIG.length;
  const cfg   = FLOW_STEP_CONFIG[idx];
  const data  = _diagramSteps[idx]; // may be undefined if no flow run yet

  // Update counter
  _counterEl.textContent = `Step ${idx + 1} of ${total}`;

  // Update nav button states
  _btnPrev.disabled = (idx === 0);
  _btnNext.disabled = (idx === total - 1);

  // Clear actor states
  [_actorBrowser, _actorServer, _actorLucid].forEach(a => {
    a.classList.remove('actor-active', 'actor-arrived', 'actor-pulse');
  });

  // Hide both packets immediately (opacity 0, no transition)
  [_packet1, _packet2].forEach(p => {
    p.classList.remove('packet-visible', 'packet-redirect', 'packet-code', 'packet-token');
    p.style.transition = 'none';
    p.style.left = '0%';
    p.textContent = '';
  });

  // Clear any running animation
  if (_diagAnimTimer) { clearTimeout(_diagAnimTimer); _diagAnimTimer = null; }

  // ── Internal step (1 or 4) ──────────────────────────────────────────────────
  if (cfg.dir === 'internal') {
    const actor = cfg.actor === 'server' ? _actorServer : _actorBrowser;
    actor.classList.add('actor-pulse');
    _calloutEl.className = 'callout-pending';
    _calloutBadge.textContent = `STEP ${idx + 1}`;

  // ── Packet animation ────────────────────────────────────────────────────────
  } else {
    const packet  = cfg.track === 1 ? _packet1 : _packet2;
    const fromActor = _actorForId(cfg.from);
    const toActor   = _actorForId(cfg.to);

    // Build packet label from real data, or fall back to default
    const packetLabel = _packetLabel(idx, data);

    // Special handling: step 5 has a two-phase animation (server→Lucid POST, Lucid→server response)
    if (idx === 4) {
      _animateStep5(packet, fromActor, toActor, data);
    } else {
      fromActor.classList.add('actor-active');

      // Position packet at start (suppress transition)
      const startPct = cfg.dir === 'right' ? '0%' : '92%';
      const endPct   = cfg.dir === 'right' ? '88%' : '4%';

      packet.textContent = packetLabel;
      if (cfg.packetClass) packet.classList.add(cfg.packetClass);
      packet.style.transition = 'none';
      packet.style.left = startPct;

      // rAF double-frame trick: let browser settle position before enabling transition
      requestAnimationFrame(() => requestAnimationFrame(() => {
        packet.style.transition = 'left 0.65s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.25s ease';
        packet.classList.add('packet-visible');
        packet.style.left = endPct;

        _diagAnimTimer = setTimeout(() => {
          fromActor.classList.remove('actor-active');
          toActor.classList.add('actor-arrived');
          _calloutEl.className = 'callout-ok';
        }, 680);
      }));
    }
  }

  // ── Callout ─────────────────────────────────────────────────────────────────
  _calloutBadge.textContent = `STEP ${idx + 1}`;
  _calloutTitle.textContent  = data ? data.label  : cfg.defaultLabel;
  _calloutDetail.textContent = data ? data.detail : cfg.defaultDetail;

  // ── Payload panel ────────────────────────────────────────────────────────────
  _renderPayload(idx, data);
}

// ── Step 5 two-phase animation (POST out → token back) ─────────────────────────

function _animateStep5(packet, fromActor, toActor, data) {
  fromActor.classList.add('actor-active');

  // Phase 1: server → Lucid (POST /token)
  const postLabel = 'POST /oauth2/token';
  packet.textContent = postLabel;
  packet.classList.add('packet-token');
  packet.style.transition = 'none';
  packet.style.left = '0%';

  requestAnimationFrame(() => requestAnimationFrame(() => {
    packet.style.transition = 'left 0.65s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.25s ease';
    packet.classList.add('packet-visible');
    packet.style.left = '88%';

    _diagAnimTimer = setTimeout(() => {
      // Packet arrives at Lucid
      fromActor.classList.remove('actor-active');
      toActor.classList.add('actor-active');

      // Brief pause then return with token
      _diagAnimTimer = setTimeout(() => {
        const tokenLabel = _tokenPreviewFromData(data);
        packet.textContent = tokenLabel;
        packet.classList.remove('packet-token');
        packet.classList.add('packet-code'); // green for "got the token"
        packet.style.transition = 'none';
        packet.style.left = '92%';

        requestAnimationFrame(() => requestAnimationFrame(() => {
          packet.style.transition = 'left 0.65s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.25s ease';
          packet.style.left = '4%';

          _diagAnimTimer = setTimeout(() => {
            toActor.classList.remove('actor-active');
            fromActor.classList.add('actor-arrived');
            _calloutEl.className = 'callout-ok';
          }, 680);
        }));
      }, 500);
    }, 680);
  }));
}

function _tokenPreviewFromData(data) {
  if (!data) return 'access_token ••••';
  const resp = data.response || {};
  const tok  = resp.access_token;
  if (tok && typeof tok === 'string') return tok.replace(/••+.*/, '••••');
  return 'access_token ••••';
}

// ── Payload panel renderer ─────────────────────────────────────────────────────

function _renderPayload(idx, data) {
  if (!data || (!data.request && !data.response)) {
    _payloadToggleBtn.classList.add('hidden');
    _payloadEl.classList.add('hidden');
    _payloadOpen = false;
    return;
  }

  _payloadToggleBtn.classList.remove('hidden');
  _payloadToggleBtn.textContent = _payloadOpen ? 'Hide payload ▴' : 'Show payload ▾';

  // Request section
  if (data.request) {
    _payloadRequest.innerHTML = _buildPayloadSection(
      '▲ sent', 'label-request', idx, data.request
    );
  } else {
    _payloadRequest.innerHTML = '';
  }

  // Response section
  if (data.response) {
    _payloadResponse.innerHTML = _buildPayloadSection(
      '▼ received', 'label-response', idx, data.response
    );
  } else {
    _payloadResponse.innerHTML = '';
  }
}

function _buildPayloadSection(label, labelClass, stepIdx, obj) {
  let html = `<div class="payload-section">`;
  html += `<div class="payload-section-label ${labelClass}">${label}</div>`;

  if (typeof obj !== 'object' || obj === null) {
    html += `<div class="payload-row"><span class="payload-val">${escapeHtml(String(obj))}</span></div>`;
    html += `</div>`;
    return html;
  }

  for (const [k, v] of Object.entries(obj)) {
    const valStr = typeof v === 'object' ? JSON.stringify(v, null, 2) : String(v);

    // Special treatment: annotate the auth URL in step 2's request.url
    if (stepIdx === 1 && k === 'url' && valStr.includes('oauth2/authorize')) {
      html += `<div class="payload-row">`;
      html += `<span class="payload-key">${escapeHtml(k)}</span>`;
      html += `<span class="payload-val">${_renderAnnotatedUrl(valStr)}</span>`;
      html += `</div>`;
    } else {
      html += `<div class="payload-row">`;
      html += `<span class="payload-key">${escapeHtml(k)}</span>`;
      html += `<span class="payload-val">${escapeHtml(valStr)}</span>`;
      html += `</div>`;
    }
  }

  html += `</div>`;
  return html;
}

// ── Annotated auth URL renderer ────────────────────────────────────────────────
// Breaks the URL into base + colour-coded query params. Each param key-value
// gets a colour tied to its OAuth meaning.

const URL_PARAM_CLASSES = {
  'client_id':     'upv-client-id',
  'scope':         'upv-scope',
  'redirect_uri':  'upv-redirect-uri',
  'state':         'upv-state',
  'response_type': 'upv-response-type',
};

function _renderAnnotatedUrl(rawUrl) {
  let urlObj;
  try { urlObj = new URL(rawUrl); } catch (_) {
    return escapeHtml(rawUrl); // fallback — render plain
  }

  const base = escapeHtml(urlObj.origin + urlObj.pathname);
  let html = `<div class="url-block">`;
  html += `<span class="url-base-line">${base}</span>`;
  html += `<div class="url-params-list">`;

  let first = true;
  urlObj.searchParams.forEach((val, key) => {
    const prefix = first ? '?' : '&amp;';
    first = false;
    const cls = URL_PARAM_CLASSES[key] || 'upv-response-type';
    const decodedVal = decodeURIComponent(val);
    html += `<div class="url-param-row">`;
    html += `<span class="url-amp">${prefix}</span>`;
    html += `<span class="url-pkey">${escapeHtml(key)}</span>`;
    html += `<span class="url-equals">=</span>`;
    html += `<span class="${cls}">${escapeHtml(decodedVal)}</span>`;
    html += `</div>`;
  });

  html += `</div></div>`;
  return html;
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function _actorForId(id) {
  return { browser: _actorBrowser, server: _actorServer, lucid: _actorLucid }[id];
}

function _packetLabel(idx, data) {
  // Try to extract a meaningful short label from real data
  if (!data) return FLOW_STEP_CONFIG[idx].defaultLabel;
  const req  = data.request  || {};
  const resp = data.response || {};

  switch (idx) {
    case 0: { // State token — show truncated value
      const tok = resp.state_token || '';
      return tok ? `state: ${tok}` : 'state token';
    }
    case 1: { // 302 redirect — show short URL hint
      return '302 → auth URL';
    }
    case 2: { // Code received
      const code = resp.code || '';
      return code ? `code: ${code}` : 'auth code';
    }
    case 3: { // State validated
      return resp.csrf_check === 'passed' ? 'state ✓ matched' : 'state check';
    }
    case 4: { // Token exchange — handled separately in _animateStep5
      return 'POST /oauth2/token';
    }
    default: return FLOW_STEP_CONFIG[idx].defaultLabel;
  }
}

function _togglePayload() {
  _payloadOpen = !_payloadOpen;
  _payloadEl.classList.toggle('hidden', !_payloadOpen);
  _payloadToggleBtn.textContent = _payloadOpen ? 'Hide payload ▴' : 'Show payload ▾';
}

function _advanceStep() {
  if (_diagramCurrent < FLOW_STEP_CONFIG.length - 1) renderStep(_diagramCurrent + 1);
}

function _retreatStep() {
  if (_diagramCurrent > 0) renderStep(_diagramCurrent - 1);
}

// ── Modal open/close ───────────────────────────────────────────────────────────

function _flowStatusUrl() {
  return _modalFlowType === 'account' ? '/auth/account-flow-status' : '/auth/flow-status';
}

function _flowAuthRoute() {
  return _modalFlowType === 'account' ? '/auth/lucid-account' : '/auth/lucid';
}

// ── Flow tab helpers ───────────────────────────────────────────────────────────

// Switch the active flow-type tab and re-render the diagram for that flow.
// Fetches from the server if we don't have a cached result yet.
async function switchFlowTab(flowType) {
  _modalFlowType = flowType;

  // Update tab active state
  $$('.flow-type-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.flow === flowType);
  });

  // Update intro text and action button label to match the selected flow
  _updateModalIntro(flowType);

  // Use cached data if available, otherwise fetch
  if (_flowCache[flowType]) {
    _applyFlowData(_flowCache[flowType]);
  } else {
    initFlowDiagram([]);  // show empty diagram while loading
    authErrorPanel.classList.add('hidden');
    authSuccessPanel.classList.add('hidden');
    try {
      const res = await fetch(_flowStatusUrl());
      if (!res.ok) return;
      const data = await res.json();
      _flowCache[flowType] = data;
      _applyFlowData(data);
    } catch (_) {}
  }
}

function _updateModalIntro(flowType) {
  const introEl = $('#auth-modal-intro');
  if (flowType === 'account') {
    introEl.innerHTML = '<strong>OAuth 2.0 Account Token Flow</strong> — uses <code>oauth2/authorizeAccount</code>. ' +
      'Produces an account-admin token needed for createUser, listUsers, and other admin operations.';
  } else {
    introEl.innerHTML = '<strong>OAuth 2.0 Authorization Code Flow</strong> — step-by-step. ' +
      'Each step shows exactly what was sent and what came back.';
  }
}

// Apply fetched flow-status data to the modal (diagram + panels)
function _applyFlowData(data) {
  initFlowDiagram(data.steps || []);
  authErrorPanel.classList.add('hidden');
  authSuccessPanel.classList.add('hidden');
  btnRetryAuth.classList.add('hidden');

  if (data.authenticated) {
    authSuccessPanel.classList.remove('hidden');
    const scopes  = (data.scopes || []).length ? data.scopes.join(', ') : 'unknown';
    const expires = data.expires_at
      ? ` Expires at ${new Date(data.expires_at + 'Z').toLocaleTimeString()}.` : '';
    authSuccessDetail.textContent =
      `Access token held in this app's memory. Scopes granted: ${scopes}.${expires} ` +
      `Token disappears when you stop python main.py — nothing written to disk.`;
    btnOpenLucid.textContent = 'Close';
    btnOpenLucid.disabled = false;
    _modalButtonMode = 'close';

  } else if (data.steps && data.steps.some(s => s.status === 'error')) {
    const errorStep = data.steps.find(s => s.status === 'error');
    authErrorPanel.classList.remove('hidden');
    $('#auth-error-label').textContent = `⚠ ${errorStep.label}`;
    authErrorDetail.textContent = errorStep.detail;
    btnRetryAuth.classList.remove('hidden');
    btnOpenLucid.textContent = 'Try again →';
    btnOpenLucid.disabled = false;
    _modalButtonMode = 'retry';
    const errIdx = data.steps.indexOf(errorStep);
    if (errIdx >= 0) renderStep(errIdx);

  } else {
    // No flow run yet for this type
    btnOpenLucid.textContent = `Auth ${_modalFlowType === 'account' ? 'Account' : 'User'} Token →`;
    btnOpenLucid.disabled = false;
    _modalButtonMode = 'launch';
  }
}

// Update the tab status badges (✓ or blank) based on server auth state
function _updateFlowTabBadges(authStatus) {
  const userOk    = authStatus?.rest?.authenticated;
  const accountOk = authStatus?.rest_account?.authenticated;
  const userBadge    = $('#flow-tab-user-status');
  const accountBadge = $('#flow-tab-account-status');
  if (userBadge)    userBadge.textContent    = userOk    ? '✓' : '';
  if (accountBadge) accountBadge.textContent = accountOk ? '✓' : '';
}

// ── Modal open/close ───────────────────────────────────────────────────────────

// Open modal in "fresh" state — no flow data yet, about to redirect
function openAuthModalFresh(flowType = 'user') {
  _modalFlowType = flowType;
  authErrorPanel.classList.add('hidden');
  authSuccessPanel.classList.add('hidden');
  btnRetryAuth.classList.add('hidden');

  // Show scope selector before the redirect; hide the flow diagram
  // (diagram is revealed after the user clicks "Authorize" and we redirect)
  $('#scope-selector').classList.remove('hidden');
  $('#auth-flow-diagram').classList.add('hidden');

  btnOpenLucid.textContent = 'Authorize with selected scopes →';
  btnOpenLucid.disabled = false;
  _modalButtonMode = 'scope-select';
  authModalOverlay.classList.remove('hidden');
  _updateModalIntro(flowType);
  $$('.flow-type-tab').forEach(t => t.classList.toggle('active', t.dataset.flow === flowType));
  // Don't call initFlowDiagram([]) yet — diagram is hidden until after redirect
}

// Open the modal on the "View Auth Flows" button — always shows both tabs,
// defaults to opening on the tab that was most recently authed (or 'user').
async function openAuthModalViewer(preferTab = 'user') {
  // Clear the cache so we get fresh data
  _flowCache.user    = null;
  _flowCache.account = null;

  // Viewer mode always shows the flow diagram, never the scope selector
  $('#scope-selector').classList.add('hidden');
  $('#auth-flow-diagram').classList.remove('hidden');

  authModalOverlay.classList.remove('hidden');

  // Fetch both flows in parallel to populate tab badges
  const [userRes, acctRes] = await Promise.allSettled([
    fetch('/auth/flow-status'),
    fetch('/auth/account-flow-status'),
  ]);

  if (userRes.status === 'fulfilled' && userRes.value.ok)
    _flowCache.user = await userRes.value.json();
  if (acctRes.status === 'fulfilled' && acctRes.value.ok)
    _flowCache.account = await acctRes.value.json();

  // Update tab badges based on auth state
  _updateFlowTabBadges({
    rest:         _flowCache.user    ? { authenticated: _flowCache.user.authenticated }    : null,
    rest_account: _flowCache.account ? { authenticated: _flowCache.account.authenticated } : null,
  });

  // Show on the preferred tab
  _modalFlowType = preferTab;
  $$('.flow-type-tab').forEach(t => t.classList.toggle('active', t.dataset.flow === preferTab));
  _updateModalIntro(preferTab);
  if (_flowCache[preferTab]) {
    _applyFlowData(_flowCache[preferTab]);
  } else {
    initFlowDiagram([]);
    btnOpenLucid.textContent = `Auth ${preferTab === 'account' ? 'Account' : 'User'} Token →`;
    btnOpenLucid.disabled = false;
    _modalButtonMode = 'launch';
  }
}

function closeAuthModal() {
  authModalOverlay.classList.add('hidden');
  if (_diagAnimTimer) { clearTimeout(_diagAnimTimer); _diagAnimTimer = null; }
}

// ── DCR Explainer Modal ────────────────────────────────────────────────────────
//
// A self-contained animated explainer for MCP's OAuth + Dynamic Client Registration
// flow. Five steps, each with an actor animation, callout, and optional payload.
// Same visual language as the OAuth modal — packet animations, actor highlights.

const DCR_STEPS = [
  {
    id: 'dcr-register',
    title: 'Dynamic Client Registration (DCR)',
    detail: 'Your server POSTs to the Lucid MCP registration endpoint with client metadata — name and redirect URI. No Developer Portal setup required. Lucid issues a fresh client_id and client_secret on the spot.',
    actorEffect: { server: 'dcr-active', lucid: null },
    arrowEffect: { track: 2, dir: 'right', packetClass: 'dcr-pkt-register', label: 'POST /oauth/register' },
    arrivedActor: 'lucid',
    arrivedEffect: 'dcr-register',
    calloutClass: 'dcr-amber',
    payload: {
      req: `POST https://mcp.lucid.app/oauth/register\nContent-Type: application/json\n\n{\n  "client_name": "lucid-api-explorer",\n  "redirect_uris": ["http://localhost:8000/mcp/callback"],\n  "grant_types": ["authorization_code", "refresh_token"]\n}`,
      res: `HTTP 201 Created\n\n{\n  "client_id": "dyn_abc123…",\n  "client_secret": "dyn_secret…",\n  "client_id_issued_at": 1740000000\n}`,
    },
  },
  {
    id: 'dcr-redirect',
    title: 'Build Authorization URL & Redirect',
    detail: 'Using the freshly issued client_id, the server builds an authorization URL and sends your browser there via a <strong>302 redirect</strong> — HTTP\'s way of saying "go here instead." Your browser follows it automatically to Lucid\'s consent screen. The URL includes a <strong>PKCE</strong> (Proof Key for Code Exchange) <strong>code_challenge</strong>: a one-way hash of a random secret. Without PKCE, anyone who intercepted the authorization code in transit could exchange it for a token themselves. With PKCE, the code is useless alone — the original secret never left the server, so only this server can complete the exchange.',
    actorEffect: { server: 'dcr-active', lucid: null },
    arrowEffect: { track: 1, dir: 'left', packetClass: 'dcr-pkt-redirect', label: '302 → Lucid consent' },
    arrivedActor: 'browser',
    arrivedEffect: 'dcr-arrived',
    calloutClass: 'dcr-ok',
    payload: {
      req: `GET https://lucid.app/oauth2/authorize\n  ?client_id=dyn_abc123…\n  &redirect_uri=http://localhost:8000/mcp/callback\n  &response_type=code\n  &code_challenge=BASE64URL(SHA256(verifier))\n  &code_challenge_method=S256\n  &scope=…`,
      res: `302 Found — browser follows redirect\nUser sees Lucid consent screen`,
    },
  },
  {
    id: 'dcr-consent',
    title: 'User Grants Consent',
    detail: 'You click "Allow" on Lucid\'s consent screen. Lucid redirects back to your server with a one-time <strong>authorization code</strong> — short-lived (~60s) and single-use. The URL also includes a <strong>state</strong> value your server set at the start. Your server checks that it matches — this is <strong>CSRF protection</strong>. CSRF (Cross-Site Request Forgery) is an attack where a malicious site tricks your browser into making a request on your behalf. The state check proves the redirect came from the same flow your server started, not from an attacker.',
    actorEffect: { server: null, lucid: 'dcr-active' },
    arrowEffect: { track: 2, dir: 'left', packetClass: 'dcr-pkt-code', label: '?code=…' },
    arrivedActor: 'server',
    arrivedEffect: 'dcr-arrived',
    calloutClass: 'dcr-ok',
    payload: {
      req: `GET http://localhost:8000/mcp/callback\n  ?code=one_time_auth_code\n  &state=csrf_token`,
      res: `Server receives code and state\nCSRF check: state matches stored value ✓`,
    },
  },
  {
    id: 'dcr-exchange',
    title: 'Token Exchange (server-to-server)',
    detail: 'The server POSTs the auth code + code_verifier to Lucid\'s token endpoint. This is server-to-server — the dynamic client_secret travels here but never touches the browser. The code_verifier proves this is the same client that initiated the flow (PKCE).',
    actorEffect: { server: 'dcr-active', lucid: null },
    arrowEffect: { track: 2, dir: 'right', packetClass: 'dcr-pkt-token', label: 'POST /oauth2/token' },
    arrivedActor: 'lucid',
    arrivedEffect: 'dcr-arrived',
    calloutClass: 'dcr-ok',
    payload: {
      req: `POST https://api.lucid.co/oauth2/token\nContent-Type: application/x-www-form-urlencoded\n\ngrant_type=authorization_code\n&code=one_time_auth_code\n&client_id=dyn_abc123…\n&client_secret=dyn_secret…\n&code_verifier=random_verifier`,
      res: `HTTP 200 OK\n\n{\n  "access_token": "Bearer eyJ…",\n  "expires_in": 3600,\n  "token_type": "Bearer"\n}`,
    },
  },
  {
    id: 'dcr-use',
    title: 'Authenticated MCP Requests',
    detail: 'Your server sends the prompt to Lucid\'s MCP server over <strong>Streamable HTTP</strong> — a transport where the request goes out as a normal HTTP POST, but the response can stream back in chunks (like how ChatGPT types its answer progressively). The MCP server interprets your intent, makes the appropriate <strong>Lucid REST API calls</strong>, and streams results back. So yes: MCP is a natural language wrapper around Lucid\'s APIs. The <code>mcp</code> package handles token attachment, streaming, and refresh invisibly.',
    actorEffect: { server: 'dcr-active', lucid: null },
    arrowEffect: null,
    streamEffect: [
      { track: 2, dir: 'right', packetClass: 'dcr-pkt-token',  label: 'prompt →'    },
      { track: 2, dir: 'left',  packetClass: 'dcr-pkt-stream', label: '← streaming' },
    ],
    arrivedActor: 'server',
    arrivedEffect: 'dcr-arrived',
    calloutClass: 'dcr-ok',
    payload: {
      req: `POST https://mcp.lucid.app/mcp\nAuthorization: Bearer eyJ…\nContent-Type: application/json\n\n// JSON-RPC: a standard format for calling remote functions over HTTP.\n// "method": what to do — "tools/call" means "run this MCP tool"\n// "params": the tool name + arguments your server decided to use\n{\n  "jsonrpc": "2.0",\n  "method": "tools/call",\n  "params": {\n    "name": "search_documents",\n    "arguments": { "query": "your prompt here" }\n  }\n}`,
      res: `HTTP 200 OK\n\n{ "content": [ { "type": "text", "text": "…results…" } ] }`,
    },
  },
];

let _dcrCurrent = 0;
let _dcrAnimTimer = null;
let _dcrPayloadOpen = false;

// DOM refs — grabbed lazily when modal opens
let _dcrActorBrowser, _dcrActorServer, _dcrActorLucid;
let _dcrPacket1, _dcrPacket2;
let _dcrBtnPrev, _dcrBtnNext;
let _dcrCounterEl;
let _dcrCalloutEl, _dcrBadgeEl, _dcrTitleEl, _dcrDetailEl;
let _dcrPayloadBtn, _dcrPayloadEl, _dcrPayloadReq, _dcrPayloadRes;

function _grabDcrRefs() {
  _dcrActorBrowser = $('#dcr-actor-browser');
  _dcrActorServer  = $('#dcr-actor-server');
  _dcrActorLucid   = $('#dcr-actor-lucid');
  _dcrPacket1      = $('#dcr-packet-1');
  _dcrPacket2      = $('#dcr-packet-2');
  _dcrBtnPrev      = $('#btn-dcr-prev');
  _dcrBtnNext      = $('#btn-dcr-next');
  _dcrCounterEl    = $('#dcr-step-counter');
  _dcrCalloutEl    = $('#dcr-callout');
  _dcrBadgeEl      = $('#dcr-callout-badge');
  _dcrTitleEl      = $('#dcr-callout-title');
  _dcrDetailEl     = $('#dcr-callout-detail');
  _dcrPayloadBtn   = $('#btn-dcr-payload');
  _dcrPayloadEl    = $('#dcr-payload');
  _dcrPayloadReq   = $('#dcr-payload-req');
  _dcrPayloadRes   = $('#dcr-payload-res');
}

function openDcrModal() {
  _grabDcrRefs();
  _dcrCurrent    = 0;
  _dcrPayloadOpen = false;

  // Reset actors
  [_dcrActorBrowser, _dcrActorServer, _dcrActorLucid].forEach(a => {
    a.className = 'dcr-actor';
    a.querySelector('.dcr-actor-icon').style.removeProperty('border-color');
  });

  // Reset packets
  [_dcrPacket1, _dcrPacket2].forEach(p => {
    p.className = 'dcr-packet';
    p.textContent = '';
    p.style.transition = 'none';
    p.style.left = '0%';
  });

  // Wire nav buttons (clone to remove old listeners)
  const newPrev = _dcrBtnPrev.cloneNode(true);
  const newNext = _dcrBtnNext.cloneNode(true);
  _dcrBtnPrev.replaceWith(newPrev); _dcrBtnPrev = newPrev;
  _dcrBtnNext.replaceWith(newNext); _dcrBtnNext = newNext;
  _dcrBtnPrev.addEventListener('click', () => { if (_dcrCurrent > 0) _dcrRenderStep(_dcrCurrent - 1); });
  _dcrBtnNext.addEventListener('click', () => { if (_dcrCurrent < DCR_STEPS.length - 1) _dcrRenderStep(_dcrCurrent + 1); });

  // Wire payload toggle
  const newToggle = _dcrPayloadBtn.cloneNode(true);
  _dcrPayloadBtn.replaceWith(newToggle); _dcrPayloadBtn = newToggle;
  _dcrPayloadBtn.addEventListener('click', () => {
    _dcrPayloadOpen = !_dcrPayloadOpen;
    _dcrPayloadEl.classList.toggle('hidden', !_dcrPayloadOpen);
    _dcrPayloadBtn.textContent = _dcrPayloadOpen ? 'Hide payload ▴' : 'Show payload ▾';
  });

  _dcrPayloadEl.classList.add('hidden');
  _dcrPayloadBtn.textContent = 'Show payload ▾';

  $('#dcr-modal-overlay').classList.remove('hidden');
  _dcrRenderStep(0);
}

function closeDcrModal() {
  $('#dcr-modal-overlay').classList.add('hidden');
  if (_dcrAnimTimer) { clearTimeout(_dcrAnimTimer); _dcrAnimTimer = null; }
}

function _actorRefForId(id) {
  if (id === 'browser') return _dcrActorBrowser;
  if (id === 'server')  return _dcrActorServer;
  if (id === 'lucid')   return _dcrActorLucid;
  return null;
}

function _dcrRenderStep(idx) {
  _dcrCurrent = idx;
  const step  = DCR_STEPS[idx];
  const total = DCR_STEPS.length;

  // Counter + nav
  _dcrCounterEl.textContent = `Step ${idx + 1} of ${total}`;
  _dcrBtnPrev.disabled = (idx === 0);
  _dcrBtnNext.disabled = (idx === total - 1);

  // Clear actor states
  [_dcrActorBrowser, _dcrActorServer, _dcrActorLucid].forEach(a => {
    a.className = 'dcr-actor';
  });

  // Hide packets immediately (suppress transition)
  [_dcrPacket1, _dcrPacket2].forEach(p => {
    p.className = 'dcr-packet';
    p.textContent = '';
    p.style.transition = 'none';
    p.style.left = '0px';
  });

  // Remove streaming state from track 2 (only active during Step 5)
  $('#dcr-track-2').classList.remove('dcr-streaming');

  if (_dcrAnimTimer) { clearTimeout(_dcrAnimTimer); _dcrAnimTimer = null; }

  // Apply actor start state
  if (step.actorEffect?.server) _dcrActorServer.classList.add(step.actorEffect.server);
  if (step.actorEffect?.lucid)  _dcrActorLucid.classList.add(step.actorEffect.lucid);

  // Animate packet
  const ae = step.arrowEffect;
  if (ae) {
    const packet = ae.track === 1 ? _dcrPacket1 : _dcrPacket2;

    packet.textContent = ae.label;
    packet.classList.add(ae.packetClass);
    packet.classList.remove('dcr-packet-dock');
    packet.style.transition = 'none';
    packet.style.left = '0px';

    requestAnimationFrame(() => requestAnimationFrame(() => {
      // Compute travel in px so long labels don't overlap destination actors.
      const trackWidth = packet.parentElement ? packet.parentElement.clientWidth : 0;
      const packetWidth = packet.offsetWidth;
      const gapPx = 12;
      const maxRight = Math.max(gapPx, trackWidth - packetWidth - gapPx);
      const startPx = ae.dir === 'right' ? gapPx : maxRight;
      const endPx = ae.dir === 'right' ? maxRight : gapPx;
      const distancePx = Math.abs(endPx - startPx);
      const durationMs = Math.min(900, Math.max(520, Math.round(distancePx * 1.35)));

      packet.style.left = `${startPx}px`;
      // Force layout so the browser applies the start position before animating.
      // eslint-disable-next-line no-unused-expressions
      packet.offsetHeight;

      // Decelerating ease for a cleaner instructional "dock" feel.
      packet.style.transition = `left ${durationMs}ms cubic-bezier(0.16, 0.84, 0.28, 1), opacity 220ms ease`;
      packet.classList.add('dcr-packet-visible');
      packet.style.left = `${endPx}px`;

      _dcrAnimTimer = setTimeout(() => {
        packet.classList.add('dcr-packet-dock');
        setTimeout(() => packet.classList.remove('dcr-packet-dock'), 280);

        if (step.actorEffect?.server) _dcrActorServer.classList.remove(step.actorEffect.server);
        const arrivedRef = _actorRefForId(step.arrivedActor);
        if (arrivedRef && step.arrivedEffect) arrivedRef.classList.add(step.arrivedEffect);
        _dcrCalloutEl.className = step.calloutClass || '';
      }, durationMs + 40);
    }));
  } else if (step.streamEffect) {
    // Streaming step — two-packet sequence: prompt right, result left
    const track2 = $('#dcr-track-2');
    track2.classList.add('dcr-streaming');
    _dcrCalloutEl.className = step.calloutClass || '';
    if (step.actorEffect?.server) _dcrActorServer.classList.add(step.actorEffect.server);
    _animateStreamPackets(step.streamEffect, step);
  } else {
    // Internal step — pulse server
    _dcrActorServer.classList.add('dcr-pulse');
    _dcrCalloutEl.className = step.calloutClass || 'dcr-pending';
  }

  // Callout text
  _dcrBadgeEl.textContent  = `STEP ${idx + 1}`;
  _dcrTitleEl.textContent  = step.title;
  _dcrDetailEl.innerHTML = step.detail;

  // Payload
  if (step.payload) {
    _dcrPayloadBtn.classList.remove('hidden');
    _dcrPayloadReq.textContent = step.payload.req;
    _dcrPayloadRes.textContent = step.payload.res;
  } else {
    _dcrPayloadBtn.classList.add('hidden');
  }
  // Collapse payload on step change
  _dcrPayloadOpen = false;
  _dcrPayloadEl.classList.add('hidden');
  _dcrPayloadBtn.textContent = 'Show payload ▾';
}

// Two-packet streaming animation for Step 5 (Streamable HTTP).
// Sends a "prompt →" packet right, then a "← streaming" packet left,
// to show the bidirectional nature of the Streamable HTTP transport.
function _animateStreamPackets(effects, step) {
  const [firstEffect, secondEffect] = effects;
  const pkt = _dcrPacket2; // track 2 always uses packet2

  // Reset packet cleanly
  pkt.className = 'dcr-packet';
  pkt.textContent = '';
  pkt.style.transition = 'none';
  pkt.style.left = '0px';

  requestAnimationFrame(() => requestAnimationFrame(() => {
    const trackWidth = pkt.parentElement?.clientWidth ?? 0;
    const gap = 12;
    const maxRight = Math.max(gap, trackWidth - (pkt.offsetWidth || 80) - gap);

    // ── First packet: prompt → (right) ──────────────────────────────────────
    pkt.textContent = firstEffect.label;
    pkt.classList.add(firstEffect.packetClass, 'dcr-packet-visible');
    pkt.style.left = `${gap}px`;
    pkt.offsetHeight; // force layout
    const dur1 = 680;
    pkt.style.transition = `left ${dur1}ms cubic-bezier(0.16, 0.84, 0.28, 1), opacity 220ms ease`;
    pkt.style.left = `${maxRight}px`;

    _dcrAnimTimer = setTimeout(() => {
      pkt.classList.add('dcr-packet-dock');
      setTimeout(() => pkt.classList.remove('dcr-packet-dock'), 280);

      // Short pause, then return packet slides back left
      setTimeout(() => {
        pkt.style.transition = 'opacity 150ms ease';
        pkt.classList.remove('dcr-packet-visible');

        setTimeout(() => {
          // ── Second packet: ← streaming (left) ───────────────────────────
          pkt.className = 'dcr-packet';
          pkt.textContent = secondEffect.label;
          pkt.classList.add(secondEffect.packetClass);
          pkt.style.transition = 'none';
          pkt.style.left = `${maxRight}px`;
          pkt.offsetHeight; // force layout
          const dur2 = 750;
          pkt.style.transition = `left ${dur2}ms cubic-bezier(0.16, 0.84, 0.28, 1), opacity 220ms ease`;
          pkt.classList.add('dcr-packet-visible');
          pkt.style.left = `${gap}px`;

          _dcrAnimTimer = setTimeout(() => {
            pkt.classList.add('dcr-packet-dock');
            setTimeout(() => pkt.classList.remove('dcr-packet-dock'), 280);
            // Stream arrives at Your Server — light it up green
            const arrivedRef = _actorRefForId(step.arrivedActor);
            if (arrivedRef && step.arrivedEffect) arrivedRef.classList.add(step.arrivedEffect);
            if (step.actorEffect?.server) _dcrActorServer.classList.remove(step.actorEffect.server);
          }, dur2 + 40);
        }, 160);
      }, 380);
    }, dur1 + 40);
  }));
}

// MCP button wiring is done inside init() below — see that function.

// ── Button wiring ──────────────────────────────────────────────────────────────

const FALLBACK_SCOPES = {
  user: [
    { scope: 'account.user:readonly', description: 'Read user accounts, emails, and profile data', endpoints: ['getUser', 'userEmailSearch', 'getUserProfile'], enterprise_only: false },
    { scope: 'user.profile', description: "Read the authenticated user's own extended profile", endpoints: ['getUserProfile'], enterprise_only: false },
    { scope: 'account.info', description: 'Read basic account information (name, plan, ID)', endpoints: ['getAccountInfo'], enterprise_only: false },
    { scope: 'lucidchart.document.content:readonly', description: 'Read Lucidchart document metadata and content', endpoints: ['searchDocuments', 'getDocument', 'getDocumentContents'], enterprise_only: false },
    { scope: 'lucidchart.document.content', description: 'Read and modify Lucidchart documents (create, import, trash)', endpoints: ['createDocument', 'importStandardImport', 'trashDocument'], enterprise_only: false },
    { scope: 'folder:readonly', description: 'List folders and read their contents', endpoints: ['getFolder', 'listFolderContents', 'listRootFolderContents'], enterprise_only: false },
    { scope: 'folder', description: 'Create, rename, trash, and restore folders', endpoints: ['createFolder', 'updateFolder', 'trashFolder', 'restoreFolder'], enterprise_only: false },
    { scope: 'offline_access', description: 'Receive a refresh token — allows renewing access without re-authenticating', endpoints: ['(refresh token — not endpoint-specific)'], enterprise_only: false },
  ],
  account: [
    { scope: 'account.user:readonly', description: 'Read user accounts, emails, and profile data', endpoints: ['listUsers'], enterprise_only: false },
    { scope: 'account.user', description: 'Read and manage user accounts (create, modify)', endpoints: ['createUser'], enterprise_only: false },
    { scope: 'lucidchart.document.content:admin.readonly', description: 'Read all account documents — Enterprise Shield accounts only.', endpoints: ['searchAccountDocuments'], enterprise_only: true },
    { scope: 'offline_access', description: 'Receive a refresh token — allows renewing access without re-authenticating', endpoints: ['(refresh token — not endpoint-specific)'], enterprise_only: false },
  ],
};

// startAuthFlow: opens scope selector (no longer auto-redirects)
function startAuthFlow(flowType = 'user') {
  openAuthModalFresh(flowType);
  openScopeSelector(flowType);
}

// openScopeSelector: fetches /auth/required-scopes and populates the checklist
async function openScopeSelector(flowType = 'user') {
  const scopeSel = $('#scope-selector');
  const scopeList = $('#scope-list');
  scopeList.innerHTML = '<div style="padding:10px 14px;font-size:11px;color:var(--text-muted)">Loading scopes…</div>';

  try {
    const res = await fetch('/auth/required-scopes');
    if (!res.ok) {
      let detail = '';
      try {
        detail = await res.text();
      } catch (_) {}
      throw new Error(detail ? `HTTP ${res.status}: ${detail}` : `HTTP ${res.status}`);
    }
    const data = sanitizeExecutionData(await res.json());
    const scopes = flowType === 'account' ? data.account : data.user;
    renderScopeList(scopes);
  } catch (err) {
    // Graceful fallback so auth is never blocked by scope-discovery failures.
    const fallback = flowType === 'account' ? FALLBACK_SCOPES.account : FALLBACK_SCOPES.user;
    renderScopeList(fallback);
    scopeList.insertAdjacentHTML(
      'afterbegin',
      `<div style="padding:10px 14px;font-size:11px;color:var(--warning-amber);border-bottom:1px solid var(--border);">
        Scope discovery failed (${escapeHtml(err.message)}). Using built-in fallback scopes.
      </div>`
    );
  }
}

// renderScopeList: build checkbox rows from the /auth/required-scopes response
function renderScopeList(scopes) {
  const list = $('#scope-list');
  list.innerHTML = '';

  scopes.forEach(item => {
    const row = document.createElement('label');
    // Enterprise-only scopes get a distinct visual treatment and start unchecked
    row.className = item.enterprise_only ? 'scope-row scope-row-enterprise' : 'scope-row';

    // Sanitise endpoint list for display — strip the parenthetical note on offline_access
    const endpointText = item.endpoints
      .filter(e => !e.startsWith('('))
      .join(', ') || '—';

    // Enterprise scopes: unchecked by default + warning badge
    const checkedAttr = item.enterprise_only ? '' : 'checked';
    const enterpriseBadge = item.enterprise_only
      ? '<span class="scope-enterprise-badge">Enterprise Shield only</span>'
      : '';

    row.innerHTML = `
      <input type="checkbox" class="scope-checkbox" value="${item.scope}" ${checkedAttr}>
      <div class="scope-row-body">
        <span class="scope-name-row">
          <code class="scope-name">${item.scope}</code>${enterpriseBadge}
        </span>
        <span class="scope-desc">${item.description || ''}</span>
        <span class="scope-endpoints">${endpointText}</span>
      </div>
    `;
    list.appendChild(row);
  });

  // Wire "⚡ Select all scopes" shortcut button
  const btnSelectAll = $('#btn-select-all-scopes');
  // Remove old listener by cloning (avoids stacking listeners on re-open)
  const freshBtn = btnSelectAll.cloneNode(true);
  btnSelectAll.parentNode.replaceChild(freshBtn, btnSelectAll);
  freshBtn.addEventListener('click', () => {
    // Select all NON-enterprise scopes — enterprise scopes stay unchecked to
    // avoid invalid_scope errors on standard OAuth clients.
    $$('#scope-list .scope-checkbox').forEach(cb => {
      const row = cb.closest('.scope-row');
      if (!row || !row.classList.contains('scope-row-enterprise')) cb.checked = true;
    });
    // Sync the "select all" footer checkbox state
    const all = [...$$('#scope-list .scope-checkbox')];
    const checkedCount = all.filter(c => c.checked).length;
    const allCheck = $('#scope-check-all');
    if (allCheck) {
      allCheck.checked = checkedCount === all.length;
      allCheck.indeterminate = checkedCount > 0 && checkedCount < all.length;
    }
    updateScopeCount();
  });

  // Wire footer "select all" checkbox
  const allCheck = $('#scope-check-all');
  if (allCheck) {
    const freshAllCheck = allCheck.cloneNode(true);
    allCheck.parentNode.replaceChild(freshAllCheck, allCheck);
    freshAllCheck.checked = true;
    freshAllCheck.addEventListener('change', e => {
      $$('#scope-list .scope-checkbox').forEach(cb => cb.checked = e.target.checked);
      freshAllCheck.indeterminate = false;
      updateScopeCount();
    });
  }

  // Wire individual checkboxes
  $$('#scope-list .scope-checkbox').forEach(cb => {
    cb.addEventListener('change', () => {
      const all = [...$$('#scope-list .scope-checkbox')];
      const checkedCount = all.filter(c => c.checked).length;
      const fc = $('#scope-check-all');
      if (fc) {
        fc.checked = checkedCount === all.length;
        fc.indeterminate = checkedCount > 0 && checkedCount < all.length;
      }
      updateScopeCount();
    });
  });

  updateScopeCount();
}

function updateScopeCount() {
  const n = $$('#scope-list input[type=checkbox]:checked').length;
  const label = $('#scope-count-label');
  if (label) label.textContent = `${n} scope${n === 1 ? '' : 's'} selected`;
}

// _launchWithSelectedScopes: gather checked scopes, build URL, redirect
function _launchWithSelectedScopes() {
  const checked = [...$$('#scope-list input[type=checkbox]:checked')].map(cb => cb.value);

  if (checked.length === 0) {
    const label = $('#scope-count-label');
    if (label) {
      label.textContent = '⚠ Select at least one scope';
      label.style.color = 'var(--error-red)';
      setTimeout(() => { label.style.color = ''; updateScopeCount(); }, 2500);
    }
    return;
  }

  // offline_access gives a refresh token — ensure it's always included
  if (!checked.includes('offline_access')) checked.push('offline_access');

  // Build the route with scopes as a query param
  const scopeParam = encodeURIComponent(checked.join(' '));
  const route = _modalFlowType === 'account'
    ? `/auth/lucid-account?scopes=${scopeParam}`
    : `/auth/lucid?scopes=${scopeParam}`;

  // Transition: hide scope selector, show flow diagram skeleton, then redirect
  $('#scope-selector').classList.add('hidden');
  $('#auth-flow-diagram').classList.remove('hidden');
  initFlowDiagram([]);
  btnOpenLucid.disabled = true;
  btnOpenLucid.textContent = 'Redirecting to Lucid…';
  _modalButtonMode = null;

  setTimeout(() => { window.location.href = route; }, 600);
}

btnOpenLucid.addEventListener('click', () => {
  if (_modalButtonMode === 'scope-select') { _launchWithSelectedScopes(); return; }
  if (_modalButtonMode === 'close')        { closeAuthModal(); return; }
  if (_modalButtonMode === 'retry')        { closeAuthModal(); startAuthFlow(_modalFlowType); return; }
  if (_modalButtonMode === 'launch')       { closeAuthModal(); startAuthFlow(_modalFlowType); return; }
});

btnReauth.addEventListener('click', () => startAuthFlow('user'));
btnRetryAuth.addEventListener('click', () => { closeAuthModal(); startAuthFlow(_modalFlowType); });
btnAuthClose.addEventListener('click', closeAuthModal);

// Single "View Auth Flows" button — opens viewer, defaults to user tab
btnViewFlows.addEventListener('click', () => openAuthModalViewer('user'));

authModalOverlay.addEventListener('click', (e) => {
  if (e.target === authModalOverlay) closeAuthModal();
});

// Wire flow-type tab clicks (delegated — tabs exist in DOM on load)
$$('.flow-type-tab').forEach(tab => {
  tab.addEventListener('click', () => switchFlowTab(tab.dataset.flow));
});

btnReauthAccount.addEventListener('click', () => startAuthFlow('account'));

// ── Sidebar navigation ─────────────────────────────────────────────────────────

function initSidebar() {
  // Surface header toggles (expand/collapse entire API surface section)
  $$('.surface-header').forEach(header => {
    header.addEventListener('click', () => {
      const surface = header.dataset.surface;
      const list = $(`#endpoints-${surface}`);
      const isExpanded = header.classList.contains('expanded');
      header.classList.toggle('expanded', !isExpanded);
      list.classList.toggle('open', !isExpanded);
    });
  });

  // Sub-group header toggles (collapsible groups within a surface endpoint list)
  $$('.endpoint-group-header').forEach(header => {
    header.addEventListener('click', () => {
      // The sub-list is always the next sibling element after the header <li>
      const sublist = header.nextElementSibling;
      if (!sublist) return;
      const isOpen = sublist.classList.contains('open');
      sublist.classList.toggle('open', !isOpen);
      header.classList.toggle('expanded', !isOpen);
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
        // Load first endpoint in that surface.
        // If it's inside a collapsed sub-group, open that group first.
        const firstItem = list.querySelector('.endpoint-item');
        if (firstItem) {
          const parentSublist = firstItem.closest('.endpoint-sublist');
          if (parentSublist && !parentSublist.classList.contains('open')) {
            parentSublist.classList.add('open');
            const groupHeader = parentSublist.previousElementSibling;
            if (groupHeader) groupHeader.classList.add('expanded');
          }
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
            ? 'Use the refresh token held in this app\'s memory to populate this field:'
            : 'Tokens are held in this app\'s memory — use the buttons below to populate this field:'}
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

    // Standard Import helper controls: template gallery + Claude generation.
    if (
      currentEndpointKey === 'importStandardImport' &&
      param.name === 'body' &&
      param.type === 'json'
    ) {
      wrapper.appendChild(renderSiGalleryControls(input));
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

function renderSiGalleryControls(targetInput) {
  const box = document.createElement('div');
  box.className = 'si-gallery';
  box.innerHTML = `
    <div class="si-gallery-title">Standard Import Gallery</div>
    <div class="si-gallery-row">
      <button class="btn-ghost btn-sm si-template-btn" data-template="flowchart">Flowchart starter</button>
      <button class="btn-ghost btn-sm si-template-btn" data-template="orgchart">Org chart starter</button>
      <button class="btn-ghost btn-sm si-template-btn" data-template="swimlane">Swimlane starter</button>
    </div>
    <div class="si-gallery-row si-gallery-claude-row">
      <input id="si-claude-prompt" class="param-input si-claude-prompt" type="text"
        placeholder="Ask Claude: 'Diagram how this app works with REST + MCP auth'" />
      <button id="btn-si-generate" class="btn-primary btn-sm">Generate with Claude</button>
    </div>
    <div id="si-gallery-status" class="si-gallery-status"></div>
  `;

  box.querySelectorAll('.si-template-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const key = btn.dataset.template;
      const tpl = SI_TEMPLATE_LIBRARY[key];
      if (!tpl) return;
      targetInput.value = JSON.stringify(tpl.document, null, 2);
      targetInput.classList.remove('error');
      const status = box.querySelector('#si-gallery-status');
      status.textContent = `Injected template: ${tpl.label}`;
      status.className = 'si-gallery-status ok';
    });
  });

  box.querySelector('#btn-si-generate').addEventListener('click', async (e) => {
    const promptEl = box.querySelector('#si-claude-prompt');
    const statusEl = box.querySelector('#si-gallery-status');
    const prompt = promptEl.value.trim();
    if (!prompt) {
      statusEl.textContent = 'Enter a prompt for Claude first.';
      statusEl.className = 'si-gallery-status err';
      return;
    }
    await generateSiWithClaude(prompt, targetInput, statusEl, e.currentTarget);
  });

  return box;
}

// ── Execution ──────────────────────────────────────────────────────────────────

btnExecute.addEventListener('click', async () => {
  if (!currentEndpointKey) return;

  const params = collectParams();
  if (params === null) {
    appendTerminalMessage("Can't send a request with missing required fields. Fill them in.", 'err');
    return;
  }

  if (currentEndpointKey === 'importStandardImport') {
    const preflight = validateStandardImportParams(params);
    const siBodyInput = $('#param-body');
    if (siBodyInput) siBodyInput.classList.remove('error');

    if (!preflight.ok) {
      if (siBodyInput) siBodyInput.classList.add('error');
      appendTerminalMessage('Standard Import preflight failed. Fix these issues and retry:', 'err');
      preflight.errors.forEach(msg => appendTerminalMessage(`• ${msg}`, 'err'));
      return;
    }

    preflight.warnings.forEach(msg => appendTerminalMessage(`⚠ Preflight warning: ${msg}`, 'out'));
  }

  const ep = ENDPOINTS[currentEndpointKey];
  await executeEndpoint(ep, params);
});

async function executeEndpoint(ep, params) {
  btnExecute.disabled = true;
  btnExecute.innerHTML = '<span class="spinner"></span>Executing...';

  const startTime = Date.now();

  // Fire architecture diagram animation immediately (we'll update status on response)
  archAnimate(ep.surface || 'rest', ep.method || 'POST', ep.urlTemplate || '', '…');

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
    const data = sanitizeExecutionData(await res.json());

    // Re-animate with real status code now that we have the response
    archAnimate(ep.surface || 'rest', ep.method || 'POST', ep.urlTemplate || '', data.status_code || res.status);

    // Update response viewer
    displayResponse(data, latency);

    // Update terminal
    renderTerminal(data);

    // Update code tab
    renderCode(data);

    recordSiSessionEvent({
      kind: 'rest_call',
      endpoint: currentEndpointKey,
      method: reqMethodFromData(data) || ep.method,
      status_code: data.status_code,
      timestamp: new Date().toISOString(),
    });

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
      const display = k.toLowerCase() === 'authorization'
        ? redactAuthHeaderValue(v)
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

  const rawBody = JSON.stringify(res.body, null, 2);
  const previewLimit = 1200;
  const truncated = rawBody.length > previewLimit;
  const bodyPreview = truncated ? `${rawBody.slice(0, previewLimit)}...` : rawBody;
  addTerminalLine('', `  body: ${bodyPreview}`, statusClass);

  if (truncated) {
    const section = terminalOutput.lastElementChild;
    const toggle = document.createElement('button');
    toggle.className = 'btn-ghost btn-sm';
    toggle.style.marginTop = '6px';
    toggle.textContent = 'Show full response body ▾';
    let expanded = false;
    toggle.addEventListener('click', () => {
      expanded = !expanded;
      const lines = section.querySelectorAll('.terminal-line');
      const lastLine = lines[lines.length - 1];
      const textSpan = lastLine.querySelector(`.terminal-${statusClass}`);
      if (textSpan) {
        textSpan.textContent = expanded ? `  body: ${rawBody}` : `  body: ${bodyPreview}`;
      }
      toggle.textContent = expanded ? 'Hide full response body ▴' : 'Show full response body ▾';
    });
    section.appendChild(toggle);
  }
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
        ? redactAuthHeaderValue(v)
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
  const safeHeaders = { ...(req.headers || {}) };
  Object.keys(safeHeaders).forEach((k) => {
    if (k.toLowerCase() === 'authorization') safeHeaders[k] = redactAuthHeaderValue(safeHeaders[k]);
  });
  const headers = JSON.stringify(safeHeaders, null, 2).replace(/^/gm, '    ').trimStart();
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
    const data = sanitizeExecutionData(await res.json());
    renderNarrative(data.narrative);
  } catch (err) {
    narrativeOutput.innerHTML = `<span style="color:var(--error-red)">Narrative unavailable: ${escapeHtml(err.message)}</span>`;
  }
}

function renderNarrative(text) {
  // Normalize markdown artifacts so beat parsing remains stable.
  const normalized = String(text || '').replace(/\*\*(.*?)\*\*/g, '$1').trim();
  // Parse four-beat structure: lines starting with ✦ BEAT or THE BEAT or WHAT THIS MEANS
  narrativeOutput.innerHTML = '';

  const beats = normalized.split(/(?=✦\s|THE REQUEST|THE RESPONSE|WHAT THIS MEANS)/);
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
    const data = sanitizeExecutionData(await res.json());
    responseEl.innerHTML = `<strong>Q: ${escapeHtml(question)}</strong><br>${escapeHtml(data.answer)}`;
  } catch (err) {
    responseEl.innerHTML = `<strong>Q: ${escapeHtml(question)}</strong><br><span style="color:var(--error-red)">Error: ${escapeHtml(err.message)}</span>`;
  } finally {
    btnFollowup.disabled = false;
    narrativeOutput.scrollTop = narrativeOutput.scrollHeight;
  }
}

// ── MCP workspace ──────────────────────────────────────────────────────────────

// Called from MCP connect/reconnect buttons and the DCR modal connect button.
// Accepts either a real click Event or a synthetic { currentTarget: el } object.
async function _mcpConnectHandler(e) {
  const btn = e.currentTarget || $('#btn-mcp-connect');
  const forceReauth = btn && btn.id === 'btn-mcp-reconnect';
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${forceReauth ? 'Re-authenticating...' : 'Connecting...'}`;
  switchTab('terminal');
  terminalOutput.innerHTML = '';
  addTerminalSection('── MCP: OAuth 2.0 + Dynamic Client Registration ─────────────');
  addTerminalLine(new Date().toLocaleTimeString(), forceReauth
    ? 'Starting MCP re-authentication handshake…'
    : 'Starting MCP auth handshake…', 'out');

  try {
    // GET /auth/mcp — backend runs DCR, returns the Lucid authorization URL
    const res = await fetch(`/auth/mcp${forceReauth ? '?force=true' : ''}`);
    const data = await res.json();

    if (data.auth_url) {
      // Show DCR step 1+2 in the terminal before the redirect
      addTerminalLine(new Date().toLocaleTimeString(), '① POST /oauth/register — Lucid issued fresh client_id + client_secret', 'ok');
      addTerminalLine('', '   No Developer Portal setup required. Credentials valid for this session only.', 'out');
      addTerminalLine(new Date().toLocaleTimeString(), '② Redirecting browser to Lucid consent screen (PKCE flow)…', 'out');
      addTerminalLine('', `   ${data.auth_url.substring(0, 90)}…`, 'out');

      // Brief pause so the terminal is visible before redirect
      await new Promise(r => setTimeout(r, 900));
      window.location.href = data.auth_url;
    } else if (data.already_authenticated) {
      addTerminalLine(new Date().toLocaleTimeString(), '✓ MCP is already connected. No new auth required.', 'ok');
      addTerminalLine('', '  Use "Re-authenticate MCP" only when you intentionally want a new OAuth session.', 'out');
      await pollAuthStatus();
      btn.disabled = false;
      btn.textContent = forceReauth ? 'Re-authenticate MCP' : 'Connect MCP →';
    } else {
      addTerminalLine(new Date().toLocaleTimeString(), `✗ MCP auth failed: ${data.error || 'No auth URL returned — check server logs'}`, 'err');
      btn.disabled = false;
      btn.textContent = forceReauth ? 'Re-authenticate MCP' : 'Connect MCP →';
    }
  } catch (err) {
    addTerminalLine(new Date().toLocaleTimeString(), `✗ MCP connect error: ${err.message}`, 'err');
    btn.disabled = false;
    btn.textContent = forceReauth ? 'Re-authenticate MCP' : 'Connect MCP →';
  }
}

// btn-mcp-connect is handled by mcpAuthBanner delegation above.

btnMcpSubmit.addEventListener('click', async () => {
  const prompt = mcpPromptInput.value.trim();
  if (!prompt) return;

  btnMcpSubmit.disabled = true;
  btnMcpSubmit.innerHTML = '<span class="spinner"></span>Submitting...';

  // Animate diagram: NL prompt flows Browser → This App → Lucid MCP
  archAnimate('mcp', 'POST', '/api/mcp/prompt', '…');

  try {
    const res = await fetch('/api/mcp/prompt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ prompt }),
    });

    const data = sanitizeExecutionData(await res.json());
    // Re-animate with real status code
    archAnimate('mcp', 'POST', '/api/mcp/prompt', data.status_code || res.status);
    renderMcpResponse(data);

    renderTerminal(data);
    renderCode(data);

    recordSiSessionEvent({
      kind: 'mcp_prompt',
      endpoint: 'mcpPrompt',
      method: 'POST',
      status_code: data.status_code,
      timestamp: new Date().toISOString(),
      prompt_preview: prompt.slice(0, 120),
    });

    // Store for on-demand narrative — same pattern as executeEndpoint (preserves API tokens)
    lastExecutionContext = data;
    narrativeOutput.innerHTML = '<span class="terminal-placeholder">Click "Get Narrative" to have Claude narrate this request.</span>';
    btnGetNarrative.classList.remove('hidden');
  } catch (err) {
    appendTerminalMessage(`MCP request failed: ${err.message}`, 'err');
  } finally {
    btnMcpSubmit.disabled = false;
    btnMcpSubmit.textContent = 'Submit';
  }
});

function renderMcpResponse(data) {
  const searchResults = (data.body && Array.isArray(data.body.search_results))
    ? data.body.search_results
    : [];

  // Structured results panel
  if (searchResults.length > 0) {
    const visible = searchResults.slice(0, 25);
    const rows = visible.map(item => {
      const title = escapeHtml(item.title || '(untitled)');
      const id = escapeHtml(item.id || '');
      const url = escapeHtml(item.url || '#');
      return `<li><a href="${url}" target="_blank" rel="noopener noreferrer">${title}</a><span class="mcp-result-id">${id}</span></li>`;
    }).join('');
    const extra = searchResults.length > visible.length
      ? `<div class="mcp-results-meta">Showing first ${visible.length} of ${searchResults.length} results. Open raw payload for full output.</div>`
      : '';
    mcpStructuredResults.innerHTML = `
      <h4>Search Results</h4>
      <div class="mcp-results-meta">MCP search tool returned <strong>${searchResults.length}</strong> matching documents.</div>
      ${extra}
      <ul class="mcp-results-list">${rows}</ul>
    `;
    mcpStructuredResults.classList.remove('hidden');
  } else {
    mcpStructuredResults.classList.add('hidden');
    mcpStructuredResults.innerHTML = '';
  }

  // Raw payload (collapsed by default)
  mcpResponseContent.textContent = JSON.stringify(data, null, 2);
  mcpResponseContent.classList.add('hidden');
  mcpRawControls.classList.remove('hidden');
  btnMcpRawToggle.textContent = 'Show raw MCP payload ▾';
  mcpResponseViewer.classList.remove('hidden');
}

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

if (btnMcpRawToggle) {
  btnMcpRawToggle.addEventListener('click', () => {
    const hidden = mcpResponseContent.classList.toggle('hidden');
    btnMcpRawToggle.textContent = hidden ? 'Show raw MCP payload ▾' : 'Hide raw MCP payload ▴';
  });
}

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

function reqMethodFromData(data) {
  return data && data.request ? data.request.method : '';
}

function recordSiSessionEvent(event) {
  siSessionEvents.push(event);
  if (siSessionEvents.length > SI_SESSION_LOG_LIMIT) siSessionEvents.shift();
}

function buildSiGenerationContext() {
  return {
    auth_status_label: authLabel ? authLabel.textContent : 'unknown',
    current_endpoint: currentEndpointKey || null,
    recent_events: siSessionEvents.slice(-10),
    known_surfaces: ['REST', 'SCIM', 'MCP'],
  };
}

async function generateSiWithClaude(prompt, targetInput, statusEl, btn) {
  btn.disabled = true;
  btn.textContent = 'Generating…';
  statusEl.textContent = 'Claude is generating Standard Import JSON...';
  statusEl.className = 'si-gallery-status';

  try {
    const res = await fetch('/ai/standard-import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt,
        context: buildSiGenerationContext(),
      }),
    });
    const data = await res.json();
    if (!data.document) {
      throw new Error(data.error || `Generation failed (${res.status})`);
    }
    targetInput.value = JSON.stringify(data.document, null, 2);
    targetInput.classList.remove('error');
    statusEl.textContent = 'Claude JSON generated and injected. Review, then click Execute.';
    statusEl.className = 'si-gallery-status ok';
  } catch (err) {
    statusEl.textContent = `Could not generate JSON: ${err.message}`;
    statusEl.className = 'si-gallery-status err';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Generate with Claude';
  }
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function redactAuthHeaderValue(value) {
  const raw = String(value || '').trim();
  const match = raw.match(/^Bearer\s+(.+)$/i);
  if (!match) return raw;
  const token = match[1].trim();
  if (!token) return 'Bearer ••••••••';
  return `Bearer ${token.slice(0, 10)}••••••••`;
}

function sanitizeExecutionData(data) {
  if (!data || typeof data !== 'object') return data;
  let copy;
  try {
    copy = JSON.parse(JSON.stringify(data));
  } catch (_) {
    return data;
  }
  if (copy.request && copy.request.headers) {
    Object.keys(copy.request.headers).forEach((k) => {
      if (k.toLowerCase() === 'authorization') {
        copy.request.headers[k] = redactAuthHeaderValue(copy.request.headers[k]);
      }
    });
  }
  return copy;
}

function validateStandardImportParams(params) {
  const errors = [];
  const warnings = [];

  const product = (params.product || '').trim().toLowerCase();
  if (!product) errors.push('Product is required (lucidchart or lucidspark).');
  else if (!['lucidchart', 'lucidspark'].includes(product)) {
    errors.push(`Product "${product}" is invalid. Use lucidchart or lucidspark.`);
  }

  const rawBody = (params.body || '').trim();
  if (!rawBody) {
    errors.push('Standard Import JSON body is required.');
    return { ok: false, errors, warnings };
  }

  let doc;
  try {
    doc = JSON.parse(rawBody);
  } catch (err) {
    errors.push(`Body is not valid JSON: ${err.message}`);
    return { ok: false, errors, warnings };
  }

  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
    errors.push('Top-level JSON must be an object.');
    return { ok: false, errors, warnings };
  }

  if (doc.version === undefined) errors.push('Missing required top-level field: "version".');
  else if (typeof doc.version !== 'number') errors.push('"version" must be a number.');
  else if (doc.version !== 1) warnings.push(`"version" is ${doc.version}; most Standard Import payloads use version 1.`);

  if (!Array.isArray(doc.pages)) {
    errors.push('Missing required top-level field: "pages" (must be an array).');
    return { ok: false, errors, warnings };
  }

  if (doc.pages.length === 0) {
    warnings.push('"pages" is empty; Lucid may create a blank document.');
  }

  doc.pages.forEach((page, idx) => {
    const n = idx + 1;
    if (!page || typeof page !== 'object' || Array.isArray(page)) {
      errors.push(`pages[${idx}] must be an object.`);
      return;
    }
    if (page.shapes !== undefined && !Array.isArray(page.shapes)) {
      errors.push(`pages[${idx}].shapes must be an array when provided.`);
    }
    if (page.lines !== undefined && !Array.isArray(page.lines)) {
      errors.push(`pages[${idx}].lines must be an array when provided.`);
    }
    if (!page.id) warnings.push(`Page ${n} has no "id".`);
    if (!page.title) warnings.push(`Page ${n} has no "title".`);

    if (Array.isArray(page.shapes)) {
      page.shapes.forEach((shape, sIdx) => {
        if (!shape || typeof shape !== 'object' || Array.isArray(shape)) {
          errors.push(`pages[${idx}].shapes[${sIdx}] must be an object.`);
          return;
        }
        if (!shape.id) warnings.push(`pages[${idx}].shapes[${sIdx}] has no "id".`);
        if (!shape.type) warnings.push(`pages[${idx}].shapes[${sIdx}] has no "type".`);

        const bb = shape.boundingBox;
        const hasLegacyCoords =
          Number.isFinite(shape.x) &&
          Number.isFinite(shape.y) &&
          Number.isFinite(shape.width) &&
          Number.isFinite(shape.height);

        if (!bb && !hasLegacyCoords) {
          errors.push(`pages[${idx}].shapes[${sIdx}] needs "boundingBox" (or x/y/width/height).`);
        }
        if (bb && (
          !Number.isFinite(bb.x) ||
          !Number.isFinite(bb.y) ||
          !Number.isFinite(bb.w) ||
          !Number.isFinite(bb.h)
        )) {
          errors.push(`pages[${idx}].shapes[${sIdx}].boundingBox must include numeric x,y,w,h.`);
        }
        if (hasLegacyCoords && !bb) {
          warnings.push(`pages[${idx}].shapes[${sIdx}] uses x/y/width/height; app will auto-convert to boundingBox.`);
        }
      });
    }

    if (Array.isArray(page.lines)) {
      page.lines.forEach((line, lIdx) => {
        if (!line || typeof line !== 'object' || Array.isArray(line)) {
          errors.push(`pages[${idx}].lines[${lIdx}] must be an object.`);
          return;
        }
        const hasEndpoints =
          line.endpoint1 && line.endpoint2 &&
          typeof line.endpoint1 === 'object' &&
          typeof line.endpoint2 === 'object';
        const hasSimpleRefs =
          typeof line.source === 'string' &&
          line.source &&
          typeof line.target === 'string' &&
          line.target;

        if (!hasEndpoints && !hasSimpleRefs) {
          errors.push(`pages[${idx}].lines[${lIdx}] must provide endpoint1/endpoint2 or source/target.`);
        }
        if (hasSimpleRefs && !hasEndpoints) {
          warnings.push(`pages[${idx}].lines[${lIdx}] uses source/target; server will normalize this line format.`);
        }
      });
    }
  });

  if (rawBody.length > 500000) {
    warnings.push(`Payload is large (${rawBody.length.toLocaleString()} chars); import may be slower.`);
  }

  return { ok: errors.length === 0, errors, warnings };
}

// ── Scope Summary Panel ───────────────────────────────────────────────────────
let _scopeSummaryOpen = false;

function openScopeSummary() {
  if (_tokenPanelOpen) closeTokenPanel();
  _scopeSummaryOpen = true;
  scopeSummaryPanel.classList.remove('hidden');
  scopeSummaryTrigger.classList.add('open');
  scopeSummaryTrigger.setAttribute('aria-expanded', 'true');
}

function closeScopeSummary() {
  _scopeSummaryOpen = false;
  scopeSummaryPanel.classList.add('hidden');
  scopeSummaryTrigger.classList.remove('open');
  scopeSummaryTrigger.setAttribute('aria-expanded', 'false');
}

function toggleScopeSummary() {
  if (_scopeSummaryOpen) closeScopeSummary();
  else openScopeSummary();
}

// ── Token Visibility Panel ─────────────────────────────────────────────────────
// Dropdown anchored to the topbar center, showing live token state for all slots.
// Opens on click, closes on outside click or Escape. Refreshes every second when
// open (for the expiry countdown). Fetches /auth/token-peek for full token detail.

const tokenPanelTrigger  = $('#token-panel-trigger');
const tokenPanel         = $('#token-panel');

let _tokenPanelOpen      = false;
let _tokenPanelInterval  = null;

function openTokenPanel() {
  if (_scopeSummaryOpen) closeScopeSummary();
  _tokenPanelOpen = true;
  tokenPanel.classList.remove('hidden');
  tokenPanelTrigger.classList.add('open');
  refreshTokenPanel();
  _tokenPanelInterval = setInterval(refreshTokenPanel, 1000);
}

function closeTokenPanel() {
  _tokenPanelOpen = false;
  tokenPanel.classList.add('hidden');
  tokenPanelTrigger.classList.remove('open');
  clearInterval(_tokenPanelInterval);
  _tokenPanelInterval = null;
}

function toggleTokenPanel() {
  if (_tokenPanelOpen) closeTokenPanel();
  else openTokenPanel();
}

async function refreshTokenPanel() {
  let peek = null;
  try {
    const res = await fetch('/auth/token-peek');
    if (res.ok) peek = await res.json();
  } catch (_) { /* server not ready */ }

  // Also grab SCIM status from /auth/status (token-peek doesn't include SCIM)
  let authStatus = null;
  try {
    const res2 = await fetch('/auth/status');
    if (res2.ok) authStatus = await res2.json();
  } catch (_) {}

  renderTokenSlot('user',    peek?.user_token    ?? null);
  renderTokenSlot('account', peek?.account_token ?? null);
  renderScimSlot(authStatus?.scim ?? null);
  renderMcpSlot(authStatus?.mcp  ?? null);
}

function renderTokenSlot(slotId, data) {
  const bodyEl   = $(`#token-${slotId}-body`);
  const statusEl = $(`#token-${slotId}-status`);
  const dotEl    = $(`#token-slot-${slotId} .token-slot-dot`);

  if (!data) {
    bodyEl.className = 'token-slot-body token-slot-empty';
    bodyEl.textContent = slotId === 'user'
      ? 'No user token. Click "Auth User Token" to authenticate.'
      : 'No account token. Click "Auth Account Token" to authenticate.';
    statusEl.textContent = 'none';
    statusEl.className = 'token-slot-badge badge-none';
    if (dotEl) dotEl.classList.add('inactive');
    return;
  }

  if (dotEl) dotEl.classList.remove('inactive');

  // Compute expiry
  const expiryHtml = buildExpiryHtml(data.expires_at);
  const isExpired  = data.expires_at ? new Date(data.expires_at + 'Z') < new Date() : false;

  statusEl.textContent = isExpired ? 'expired' : 'active';
  statusEl.className   = 'token-slot-badge ' + (isExpired ? 'badge-expired' : 'badge-active');

  // Build rows
  const rows = [];
  rows.push(fieldRow('type',    data.token_type || 'Bearer'));
  rows.push(fieldRow('preview', `<span class="value-mono">${escapeHtml(data.preview || '')}</span>`));
  rows.push(fieldRow('expires', expiryHtml));
  rows.push(fieldRow('refresh', data.has_refresh_token
    ? `<span style="color:var(--terminal-green)">yes — ${escapeHtml(data.refresh_token_preview || '')}</span>`
    : '<span style="color:var(--text-muted)">no</span>'));

  // Scopes row
  const scopeHtml = data.scopes && data.scopes.length
    ? data.scopes.map(s => `<span class="scope-tag" style="font-size:9px">${escapeHtml(s)}</span>`).join('')
    : '<span style="color:var(--text-muted)">none</span>';
  rows.push(`<div class="token-field"><span class="token-field-key">scopes</span><div class="token-scopes">${scopeHtml}</div></div>`);

  bodyEl.className = 'token-slot-body';
  bodyEl.innerHTML = rows.join('');
}

function renderScimSlot(scimStatus) {
  const bodyEl   = $('#token-scim-body');
  const statusEl = $('#token-scim-status');
  const dotEl    = document.querySelector('#token-slot-scim .token-slot-dot');

  const authenticated = scimStatus?.authenticated ?? false;

  if (!authenticated) {
    bodyEl.className = 'token-slot-body token-slot-empty';
    bodyEl.textContent = 'No SCIM token. Set LUCID_SCIM_TOKEN in .env.';
    statusEl.textContent = 'none';
    statusEl.className = 'token-slot-badge badge-none';
    if (dotEl) dotEl.classList.add('inactive');
    return;
  }

  if (dotEl) dotEl.classList.remove('inactive');
  statusEl.textContent = 'static';
  statusEl.className   = 'token-slot-badge badge-static';
  bodyEl.className = 'token-slot-body';
  bodyEl.innerHTML = fieldRow('type', 'Bearer (static)') +
    fieldRow('source', '.env LUCID_SCIM_TOKEN') +
    fieldRow('expiry', '<span style="color:var(--text-muted)">no expiry — rotate manually</span>');
}

function renderMcpSlot(mcpStatus) {
  const bodyEl   = $('#token-mcp-body');
  const statusEl = $('#token-mcp-status');
  const dotEl    = document.querySelector('#token-slot-mcp .token-slot-dot');

  const authenticated = mcpStatus?.authenticated ?? false;

  if (!authenticated) {
    bodyEl.className = 'token-slot-body token-slot-empty';
    bodyEl.textContent = 'No MCP session. Click "Connect MCP →" to authenticate.';
    statusEl.textContent = 'none';
    statusEl.className = 'token-slot-badge badge-none';
    if (dotEl) dotEl.classList.add('inactive');
    return;
  }

  if (dotEl) dotEl.classList.remove('inactive');
  statusEl.textContent = 'active';
  statusEl.className   = 'token-slot-badge badge-active';
  bodyEl.className = 'token-slot-body';
  bodyEl.innerHTML =
    fieldRow('type',   'Bearer (OAuth 2.0)') +
    fieldRow('method', 'Dynamic Client Registration') +
    fieldRow('expiry', '<span style="color:var(--text-muted)">managed by mcp package</span>') +
    fieldRow('note',   '<span style="color:var(--text-muted)">no manual setup — server registered itself</span>');
}

function fieldRow(key, valueHtml) {
  return `<div class="token-field"><span class="token-field-key">${key}</span><span class="token-field-value">${valueHtml}</span></div>`;
}

function buildExpiryHtml(expiresAt) {
  if (!expiresAt) return '<span style="color:var(--text-muted)">unknown</span>';
  // expires_at from server is UTC ISO without trailing Z — add it
  const expiresDate = new Date(expiresAt + 'Z');
  const nowMs       = Date.now();
  const diffMs      = expiresDate - nowMs;
  const diffSec     = Math.floor(diffMs / 1000);

  if (diffSec <= 0) {
    return `<span class="token-expiry-expired">expired ${formatDuration(-diffSec)} ago</span>`;
  }
  const cls = diffSec < 300 ? 'token-expiry-warning' : 'token-expiry-ok';
  return `<span class="${cls}">in ${formatDuration(diffSec)} (${expiresDate.toLocaleTimeString()})</span>`;
}

function formatDuration(totalSec) {
  if (totalSec < 60) return `${totalSec}s`;
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  if (min < 60) return sec > 0 ? `${min}m ${sec}s` : `${min}m`;
  const hr = Math.floor(min / 60);
  const rem = min % 60;
  return rem > 0 ? `${hr}h ${rem}m` : `${hr}h`;
}

// Close on outside click
document.addEventListener('click', (e) => {
  if (_tokenPanelOpen && !tokenPanel.contains(e.target) && !tokenPanelTrigger.contains(e.target)) {
    closeTokenPanel();
  }
  if (_scopeSummaryOpen && !scopeSummaryPanel.contains(e.target) && !scopeSummaryTrigger.contains(e.target)) {
    closeScopeSummary();
  }
});

// Close on Escape
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && _tokenPanelOpen) closeTokenPanel();
  if (e.key === 'Escape' && _scopeSummaryOpen) closeScopeSummary();
});


// ── Architecture Diagram ───────────────────────────────────────────────────────
// Persistent sidebar mini-diagram that lights up the request path in real-time.
// Three actors: Browser → This App → Lucid
// Two arrows: arch-arrow-browser-app, arch-arrow-app-lucid
// Arrow states: default (idle) | arch-flowing (request in flight) | arch-returning (response)

const ARCH_LS_KEY = 'lucid_arch_collapsed';

function initArch() {
  const toggle  = $('#arch-toggle');
  const body    = $('#arch-body');
  const chevron = $('#arch-chevron');
  if (!toggle || !body) return;

  // Restore saved preference (default: collapsed)
  const saved = localStorage.getItem(ARCH_LS_KEY);
  const startExpanded = saved === 'expanded';
  if (startExpanded) {
    body.classList.remove('hidden');
    toggle.setAttribute('aria-expanded', 'true');
  }

  toggle.addEventListener('click', () => {
    const isOpen = !body.classList.contains('hidden');
    if (isOpen) {
      body.classList.add('hidden');
      toggle.setAttribute('aria-expanded', 'false');
      localStorage.setItem(ARCH_LS_KEY, 'collapsed');
    } else {
      body.classList.remove('hidden');
      toggle.setAttribute('aria-expanded', 'true');
      localStorage.setItem(ARCH_LS_KEY, 'expanded');
    }
  });
}

/**
 * Animate the architecture diagram for a request/response cycle.
 *
 * @param {'rest'|'scim'|'mcp'} surface  - Which API surface is being called
 * @param {string} method                - HTTP method (GET, POST, etc.)
 * @param {string} urlHint               - Short URL or endpoint label for hover tooltip
 * @param {number|string} statusCode     - HTTP status received (for return arrow)
 */
function archAnimate(surface, method, urlHint, statusCode) {
  const arrowBrowserApp = $('#arch-arrow-browser-app');
  const arrowAppLucid   = $('#arch-arrow-app-lucid');
  const labelBrowserApp = $('#arch-label-browser-app');
  const labelAppLucid   = $('#arch-label-app-lucid');
  const actorBrowser    = $('#arch-actor-browser');
  const actorApp        = $('#arch-actor-app');
  const actorLucid      = $('#arch-actor-lucid');

  if (!arrowBrowserApp || !arrowAppLucid) return;

  // Clear any previous animation state immediately
  [arrowBrowserApp, arrowAppLucid].forEach(a => {
    a.classList.remove('arch-flowing', 'arch-returning');
  });
  [actorBrowser, actorApp, actorLucid].forEach(a => {
    a.classList.remove('arch-active');
  });

  // Compose plain-English labels and technical hover hints
  const techLabel = method && urlHint ? `${method} ${urlHint}` : (urlHint || 'request');
  const statusLabel = statusCode ? `${statusCode}` : 'response';

  // Phase 1: Browser → This App (request received by the app)
  actorBrowser.classList.add('arch-active');
  arrowBrowserApp.classList.add('arch-flowing');
  labelBrowserApp.textContent  = 'your request';
  labelBrowserApp.title        = techLabel;

  // Phase 2 (after 400ms): This App → Lucid (proxied call to Lucid APIs)
  const t1 = setTimeout(() => {
    actorBrowser.classList.remove('arch-active');
    actorApp.classList.add('arch-active');
    arrowAppLucid.classList.add('arch-flowing');
    labelAppLucid.textContent = 'token attached';
    labelAppLucid.title       = `Bearer token → ${surface.toUpperCase()} API`;
  }, 400);

  // Phase 3 (after 900ms): Lucid responds → This App
  const t2 = setTimeout(() => {
    actorApp.classList.remove('arch-active');
    actorLucid.classList.add('arch-active');
    arrowAppLucid.classList.remove('arch-flowing');
    arrowAppLucid.classList.add('arch-returning');
    labelAppLucid.textContent = 'response';
    labelAppLucid.title       = `HTTP ${statusLabel} from Lucid`;
  }, 900);

  // Phase 4 (after 1300ms): This App → Browser (JSON returned)
  const t3 = setTimeout(() => {
    actorLucid.classList.remove('arch-active');
    actorApp.classList.add('arch-active');
    arrowBrowserApp.classList.remove('arch-flowing');
    arrowBrowserApp.classList.add('arch-returning');
    labelBrowserApp.textContent = 'returned to you';
    labelBrowserApp.title       = `HTTP ${statusLabel}`;
  }, 1300);

  // Phase 5 (after 2200ms): Reset to idle — restore static route labels
  const t4 = setTimeout(() => {
    actorApp.classList.remove('arch-active');
    arrowBrowserApp.classList.remove('arch-returning');
    arrowAppLucid.classList.remove('arch-returning');
    labelBrowserApp.textContent = 'HTTP · localhost:8000';
    labelBrowserApp.title       = '';
    labelAppLucid.textContent   = 'HTTPS · Lucid APIs';
    labelAppLucid.title         = '';
  }, 2200);
}


// ── Init ───────────────────────────────────────────────────────────────────────

function init() {
  initSidebar();
  initArch();
  tokenPanelTrigger.addEventListener('click', toggleTokenPanel);
  scopeSummaryTrigger.addEventListener('click', toggleScopeSummary);
  pollAuthStatus();
  setInterval(pollAuthStatus, 15000); // Poll every 15s to keep status fresh
  // handleOAuthRedirect last — it may open the modal which reads DOM state
  handleOAuthRedirect();

  // ── MCP button wiring ────────────────────────────────────────────────────────
  // Must live inside init() so it runs after DOMContentLoaded — the same pattern
  // used by every other button in this file. Top-level addEventListener calls
  // run at parse time and can silently halt the JS engine if any $() returns null.

  // DCR modal close/overlay buttons
  $('#dcr-modal-close').addEventListener('click', closeDcrModal);
  $('#btn-dcr-close').addEventListener('click', closeDcrModal);
  $('#dcr-modal-overlay').addEventListener('click', (e) => {
    if (e.target === $('#dcr-modal-overlay')) closeDcrModal();
  });
  // "Connect MCP now →" button inside the DCR modal
  $('#btn-dcr-connect').addEventListener('click', () => {
    closeDcrModal();
    _mcpConnectHandler({ currentTarget: $('#btn-mcp-connect') });
  });

  // MCP banner buttons are fixed elements in the DOM; bind directly for reliability.
  const btnMcpConnect = $('#btn-mcp-connect');
  const btnMcpReconnect = $('#btn-mcp-reconnect');
  $$('.btn-mcp-how').forEach((btn) => btn.addEventListener('click', openDcrModal));
  if (btnMcpConnect) btnMcpConnect.addEventListener('click', (ev) => _mcpConnectHandler(ev));
  if (btnMcpReconnect) btnMcpReconnect.addEventListener('click', (ev) => _mcpConnectHandler(ev));
}

document.addEventListener('DOMContentLoaded', init);
