# Part 3: Hands-On Training — Lucid API Explorer
### Revised draft · April 2026
#### Audience: Customer Operations support specialists with no coding background

---

> **REVISION NOTES FOR TRAINING LEAD**
> This is a corrected version of Part 3 only. Parts 1 and 2 are unchanged.
> All changes are marked with `[CHANGED]`, `[ADDED]`, or `[REMOVED]` tags in this draft.
> A plain summary of every change appears at the bottom of this file.

---

## What Is the Lucid API Explorer?

It's a lightweight local web app built specifically for this training. It runs on your machine, connects to your Lucid account using credentials you set up, and gives you a clean interface for making API calls — without needing to write code or use cURL directly.

Under the hood, it's doing the same thing a developer's script would do: building HTTP requests, sending them to Lucid's API endpoints, and displaying the responses.

The app covers three of Lucid's API surfaces from one interface:
- **REST API** — document management, user management, collaboration
- **SCIM API** — enterprise user provisioning
- **MCP Server** — natural-language interface powered by Claude

For this training we'll focus on the REST API.

---

## Setup

### Before you start: what you'll need

You'll need four things in hand before completing setup. Collect them first so you're not context-switching mid-step.

| What you need | Where to get it |
|---|---|
| Lucid REST OAuth Client ID | Lucid Developer Portal (developer.lucid.co) |
| Lucid REST OAuth Client Secret | Same place — same client |
| Lucid SCIM Bearer Token | Lucid Admin Panel → Security → API Tokens |
| Anthropic API Key | console.anthropic.com |

**`[ADDED]`** The original doc only mentioned Client ID. The app requires all four credentials above. Missing any one of them will cause parts of the app to silently disable themselves.

---

### Step 1: Register your OAuth client in the Developer Portal

**`[CHANGED]`** The original step said "copy your Client ID." There's more to it.

1. Go to [developer.lucid.co](https://developer.lucid.co)
2. Log in with your Lucid account
3. Open your API client (or create one if none exists)
4. Copy both the **Client ID** and the **Client Secret**
5. In the client's settings, add **two** authorized redirect URIs:
   - `http://localhost:8000/callback`
   - `http://localhost:8000/callback-account`

   Both are required. The first handles user-level auth; the second handles account-level auth for admin operations like creating users and listing all users. If either is missing, that OAuth flow will fail with an error from Lucid.

6. Save the client

> **Why two redirect URIs?** Lucid has two distinct OAuth authorization flows: one that acts as the signed-in user, and one that acts on behalf of the account (for admin operations). The Explorer uses both. Each flow has its own redirect address.

---

### Step 2: Configure the app

The app reads your credentials from a file called `.env` in the project folder. This file is never shared or uploaded — it stays on your machine.

Open the `.env` file (it's in the `lucid-api-explorer` folder) and fill in your values. It should look like this:

```
LUCID_CLIENT_ID=your_client_id_here
LUCID_CLIENT_SECRET=your_client_secret_here
LUCID_REDIRECT_URI=http://localhost:8000/callback
LUCID_ACCOUNT_REDIRECT_URI=http://localhost:8000/callback-account
LUCID_SCIM_TOKEN=your_scim_bearer_token_here
ANTHROPIC_API_KEY=your_anthropic_api_key_here
```

**`[CHANGED]`** The original doc showed `CLIENT_ID=` and `CLIENT_SECRET=`. The app requires the full variable names `LUCID_CLIENT_ID=` and `LUCID_CLIENT_SECRET=`. Using the short names means the app will start but silently fail all API calls.

**`[ADDED]`** `LUCID_SCIM_TOKEN` and `ANTHROPIC_API_KEY` are also required and were not in the original setup steps. Without `ANTHROPIC_API_KEY`, the Claude narrative panel (which explains what each API call is doing) won't work.

> **You don't need to change** `LUCID_REDIRECT_URI` or `LUCID_ACCOUNT_REDIRECT_URI` — the defaults shown above are correct for local development. Just make sure they match what you registered in Step 1.

> **Leave the MCP section alone.** The app handles MCP authentication automatically. You don't need to put any MCP credentials in `.env`.

---

### Step 3: Verify your setup

**`[ADDED]`** This step was not in the original doc. The project includes a diagnostic script that catches common problems before you try to start the app.

After saving your `.env`, run:

```
python scripts/doctor.py
```

You'll see a checklist. Green checkmarks mean that credential or configuration is valid. Red marks tell you exactly what's missing or wrong. Fix anything flagged before moving on.

---

### Step 4: Start the app

**`[CHANGED]`** The original doc said `source venv/bin/activate`. The project uses a dot-prefixed virtual environment folder (`.venv`). The correct command is:

```
source .venv/bin/activate
```

Full sequence from scratch:

```
cd dev
cd lucid-api-explorer
source .venv/bin/activate
python main.py
```

You should see output like:

```
INFO:     Started server process [12345]
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

Open your browser and go to **http://localhost:8000**.

**Important:** Keep the terminal open while you work. If you close it or press Control+C, the server stops and the browser will lose connection. That's expected — just restart with `python main.py`.

> **Why `.venv` instead of `venv`?** Both names create a Python virtual environment — they're functionally identical. This project uses `.venv` (with the dot) because it follows current Python tooling conventions. The dot just means the folder is hidden by default in file explorers.

---

### Step 5: Authenticate with the REST API

**`[ADDED]`** The original doc didn't include this step, but it's required before you can make any REST API calls.

The app needs an OAuth access token before it can call Lucid on your behalf. This happens through a browser-based flow:

1. In the Explorer, look at the top of the page — you'll see an **"Auth User Token"** button
2. Click it to open the OAuth flow panel
3. Review the scopes (permissions) the app will request
4. Click **"Authorize with Lucid"** — you'll be redirected to Lucid's login page
5. Log in and approve the permissions
6. You'll be redirected back to the Explorer automatically
7. The token status in the top bar should now show a green badge

You'll also see **"Auth Account Token"** — this is for admin operations (creating users, listing all account users). Click it and follow the same flow to authenticate that as well.

> **Why two separate auth flows?** User-token calls act as you personally. Account-token calls act on behalf of the whole account — they require admin-level permissions and use a different Lucid authorization endpoint. The Explorer manages both separately.

Once both are authenticated, you're ready for the exercises.

---

## Exercises

> **Before starting:** Make sure both token indicators in the top bar show green. If either is red, go back to Step 5.

### How the Explorer interface works

**`[ADDED]`** A brief orientation that was missing from the original doc.

The left sidebar lists all available endpoints, organized by category (Documents, Users, Collaboration, etc.). Click any endpoint to open it in the main workspace. You'll see:

- **What it does** — a plain-English description
- **Parameters** — input fields for the values the endpoint needs (document ID, email address, etc.)
- **Execute** — sends the request
- **Response panel** — shows the raw JSON response, the HTTP status code, and the full request/response headers
- **Claude Narrative panel** (bottom) — after each call, click "Explain this" for a plain-English walkthrough of exactly what happened and why

---

### Exercise 1: Create a Document

**`[CHANGED]`** The original doc said "Select the POST /documents endpoint." The Explorer doesn't use raw REST paths — endpoints have names. The correct one is `createDocument`.

Steps:

1. In the left sidebar, under **Documents**, click **createDocument**
2. In the **Title** field, enter a name for your document (something you'll recognize — for example, "API Training Test")
3. In the **Document Type** field, select **lucidchart** (or leave it as the default)
4. Click **Execute**

What to look for in the response:

- **Status code: 200** — the document was created successfully
- **Response body** — a JSON object containing the document's `documentId`, `title`, and a direct URL to open it in Lucid

**Copy the `documentId` value** — you'll need it in the next three exercises.

> **What just happened?** The Explorer built a `POST` request to `https://api.lucid.co/documents`, included your access token in the Authorization header, and sent a JSON body with the title and document type you entered. Lucid created the document and returned its details. This is exactly what a developer's script does — the Explorer just removes the code.

> **Note on `createDocument` vs. `importStandardImport`:** There's also an `importStandardImport` endpoint in the sidebar for creating documents with pre-defined content. `createDocument` creates a blank document — the right starting point for this exercise.

---

### Exercise 2: Find Your Document

**`[CHANGED]`** The original doc said "Select the GET /documents endpoint." The correct endpoint name in the Explorer is `searchAccountDocuments`.

Steps:

1. In the sidebar under **Documents**, click **searchAccountDocuments**
2. Leave the parameters at their defaults (or enter your document name in the **Title** field to filter results)
3. Click **Execute**

You'll get back a list of documents in your account. Find the one you created by name or by matching the `documentId` you copied in Exercise 1.

> **Why does this matter in support?** When a customer says "I created a document via API but I can't find it in my account," this is the call you walk them through. If the document appears here but not in the app UI, the issue is usually folder placement or account filtering. If it doesn't appear here either, the creation call likely failed silently.

> **Also available:** `searchDocuments` searches only documents in the authenticated user's personal folders. `searchAccountDocuments` searches across the whole account — more useful for support scenarios.

---

### Exercise 3: Add a Collaborator

**`[CHANGED]`** The original doc said "Select the POST /documents/{id}/collaborators endpoint." The correct endpoint name in the Explorer is `putDocumentUserCollaborator`.

Steps:

1. In the sidebar under **Collaboration**, click **putDocumentUserCollaborator**
2. In the **Document ID** field, enter the `documentId` from Exercise 1
3. In the **User ID** field, enter the Lucid User ID of the person to add (not their email — their numeric user ID)
4. In the **Role** field, select a permission level (e.g., `editor` or `viewer`)
5. Click **Execute**

A successful response returns a **200 OK** with the collaborator's details.

To verify: open the document in the Lucid web app and check the sharing panel — the collaborator should now appear.

> **`[ADDED]` Finding a User ID:** Lucid's collaboration endpoints use numeric User IDs, not email addresses. To find a user's ID, use the **userEmailSearch** endpoint (under Users in the sidebar) — enter their email address and the response will include their numeric user ID. This is a common source of confusion for customers too.

---

### Exercise 4: Trash the Document

**`[CHANGED]`** Two corrections from the original doc:
1. The endpoint name was `DELETE /documents/{id}`. The correct name in the Explorer is **`trashDocument`**.
2. The original doc said to expect "204 No Content." The actual response is different — see below.

Steps:

1. In the sidebar under **Documents**, click **trashDocument**
2. In the **Document ID** field, enter your `documentId`
3. Click **Execute**

A successful response returns a **200 OK** (not 204) confirming the document was moved to trash.

> **Trash ≠ Delete.** The Lucid API moves documents to trash rather than permanently deleting them — matching what happens when you trash something in the Lucid UI. A trashed document can be recovered. There is no permanent-delete endpoint in the current API. This is important context for customers who expect a DELETE call to immediately destroy content.

---

## Bonus Exercises

**`[ADDED]`** These weren't in the original doc. They're valuable for support scenarios.

### Bonus A: Look up a User

1. In the sidebar under **Users**, click **userEmailSearch**
2. Enter a Lucid user's email address
3. Execute — you'll get back their User ID and account details

This is the first call to make when a customer says "I'm getting a 403 on this user ID" — verify the user exists and note their ID.

---

### Bonus B: Use the Claude Narrative Panel

After any successful API call:

1. Look at the bottom panel of the Explorer
2. Click the **Claude Narrative** tab (if it isn't already selected)
3. Click **"Explain this call"**

Claude will give you a four-part explanation: what the request was, what parameters it used, what Lucid returned, and what it means in plain English. You can also type follow-up questions in the text box below.

This panel is useful both for learning and for support — if a customer sends you a confusing API response, you can replicate their call in the Explorer and use this feature to help interpret it.

---

### Bonus C: Try the SCIM API

1. In the left sidebar, click **SCIM** to switch API surfaces
2. Under **Users**, click **scimGetAllUsers**
3. Execute

SCIM uses a static bearer token (which you set in `.env` earlier) rather than OAuth. The Explorer handles this automatically — no separate auth flow.

---

## Troubleshooting the Explorer

**`[CHANGED]`** The troubleshooting table from the original doc had one incorrect entry. Revised below.

| Problem | Fix |
|---|---|
| Browser says "site can't be reached" | Server isn't running. Go to your terminal and run `python main.py` again. |
| Getting 401 errors on all requests | Your OAuth token may not be set. Go to the top of the Explorer and click **"Auth User Token"** or **"Auth Account Token"** and complete the flow. If you've already done that, the token may have expired — re-authenticate. |
| Getting errors on all requests with no 401 | Check that your `.env` file has the correct variable names (`LUCID_CLIENT_ID`, `LUCID_CLIENT_SECRET` — not `CLIENT_ID`, `CLIENT_SECRET`). Restart the server after editing `.env`. |
| "venv" not found or activation fails | **`[CHANGED]`** The project uses `.venv` (not `venv`). Try: `source .venv/bin/activate` |
| App behavior differs from what you were shown | Your local code may be outdated. In terminal, run `git pull` — then restart the server. |
| Claude Narrative panel shows nothing | Check that `ANTHROPIC_API_KEY` is set in your `.env`. Restart the server after adding it. |
| Doctor script shows red checkmarks | Follow the specific error messages from `python scripts/doctor.py`. The most common cause is a missing or misnamed variable in `.env`. |

---

## What the Virtual Environment Is (and Why It Matters)

When you ran `source .venv/bin/activate`, you activated a Python virtual environment. This is a self-contained snapshot of the specific Python version and package versions the app was built with — so it works consistently regardless of what's installed on your machine.

You don't need to manage it. Just activate it before running the app. If something seems broken, type `deactivate` in the terminal and then `source .venv/bin/activate` again.

> **`[CHANGED]`** The original doc referred to `venv`. The correct folder name is `.venv` (with a dot prefix). This is the only change to this section.

---

## Summary of All Changes

*For the training lead reviewing this revision.*

| # | What changed | Why |
|---|---|---|
| 1 | `.env` variable names corrected from `CLIENT_ID` / `CLIENT_SECRET` to `LUCID_CLIENT_ID` / `LUCID_CLIENT_SECRET` | App uses prefixed names; unprefixed names are silently ignored |
| 2 | Added `LUCID_SCIM_TOKEN` and `ANTHROPIC_API_KEY` to `.env` setup | Both required; missing them disables SCIM and the Claude Narrative panel |
| 3 | Added `LUCID_REDIRECT_URI` and `LUCID_ACCOUNT_REDIRECT_URI` to `.env` setup | Needed for OAuth flows; two separate URIs must be registered in Developer Portal |
| 4 | Setup Step 1 expanded to include Client Secret and redirect URI registration | Original step said "copy your Client ID" only — insufficient |
| 5 | Added Step 3: run `python scripts/doctor.py` | Catches common setup errors before they become confusing runtime failures |
| 6 | `source venv/bin/activate` corrected to `source .venv/bin/activate` | Folder is named `.venv` in this project |
| 7 | Added Step 5: authenticate OAuth tokens in the app | Required before any REST calls work; was missing entirely |
| 8 | Exercise 1: `POST /documents` → `createDocument` | App uses named endpoint keys, not raw REST paths |
| 9 | Exercise 2: `GET /documents` → `searchAccountDocuments` | Correct endpoint name; also added note about `searchDocuments` vs `searchAccountDocuments` |
| 10 | Exercise 3: `POST /documents/{id}/collaborators` → `putDocumentUserCollaborator` | Correct endpoint name; also added note about needing User ID not email |
| 11 | Exercise 4: `DELETE /documents/{id}` → `trashDocument` | Correct endpoint name; permanent delete doesn't exist |
| 12 | Exercise 4: expected response corrected from "204 No Content" to "200 OK" | `trashDocument` returns 200, not 204; also added explanation of trash vs. permanent delete |
| 13 | Added orientation section explaining how the Explorer interface works | New users need this before the exercises make sense |
| 14 | Added three bonus exercises (userEmailSearch, Claude Narrative, SCIM) | Useful for support scenarios; covers features not in original doc |
| 15 | Troubleshooting table: 401 entry corrected to describe OAuth re-auth flow | Original pointed to `.env` file but root cause for 401s is usually missing OAuth token |
| 16 | Troubleshooting table: added `.env variable name mismatch` entry | Common error not covered |
| 17 | Troubleshooting table: added Claude Narrative not working entry | Missing `ANTHROPIC_API_KEY` is a likely setup problem |
| 18 | Troubleshooting table: added doctor script entry | New step, deserves a troubleshooting row |
| 19 | "What the virtual environment is" section: `venv` → `.venv` | Matches actual folder name |

---

*Questions? Reach out to your training lead or post in the customer ops Slack channel.*
