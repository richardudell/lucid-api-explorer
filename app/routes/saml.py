"""
app/routes/saml.py — SAML 2.0 IdP HTTP endpoints.

Routes:

  GET  /saml/metadata
       Returns IdP metadata XML. Point Lucid's "IdP Metadata URL" here,
       or copy-paste the XML into Lucid's admin panel manually.

  GET  /saml/sso
  POST /saml/sso
       The IdP SSO endpoint. Lucid redirects the browser here when SSO is
       triggered. We generate and sign a SAMLResponse, then render an
       auto-submitting HTML form that POSTs it to Lucid's ACS URL.
       Query params:
         SAMLRequest    — base64 AuthnRequest from SP (optional, SP-initiated)
         RelayState     — opaque SP state token (passed through unchanged)
         fault          — fault injection key for break-it mode

  POST /api/saml/config
       Update SP-side config (acs_url, sp_entity_id, attribute values).

  GET  /api/saml/config
       Return the current config (cert, entity IDs, etc.) — never returns
       the private key to the browser.

  POST /api/saml/generate-cert
       Regenerate the RSA keypair and self-signed certificate.

  POST /api/saml/test-assertion
       Generate and return a SAMLResponse without POSTing it to Lucid.
       Used by the educational dry-run mode.

  GET  /api/saml/narrative
       Ask Claude to narrate the most recent SAML flow.
"""

import base64
import logging
from typing import Any

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from app.services import saml_idp
from app.services.ai_client import generate_saml_narrative

log = logging.getLogger(__name__)

router = APIRouter(tags=["saml"])

# ── In-memory store for last SAML execution (for Claude narrative) ──────────────
_last_saml_execution: dict[str, Any] = {}


# ── GET /saml/metadata ──────────────────────────────────────────────────────────

@router.get("/saml/metadata", response_class=Response)
async def idp_metadata() -> Response:
    """
    Serve IdP metadata XML.
    Content-Type: application/samlmetadata+xml
    """
    config = saml_idp.load_config()
    if not config.get("cert_pem"):
        # Auto-generate cert on first metadata request if none exists yet
        config = saml_idp.generate_certificate()
        log.info("Auto-generated SAML certificate on first /saml/metadata request")

    xml = saml_idp.build_idp_metadata_xml(config)
    return Response(
        content=xml,
        media_type="application/samlmetadata+xml",
        headers={"Content-Disposition": 'attachment; filename="idp-metadata.xml"'},
    )


# ── GET + POST /saml/sso ────────────────────────────────────────────────────────

@router.get("/saml/sso", response_class=HTMLResponse)
async def sso_get(
    SAMLRequest: str | None = Query(default=None),
    RelayState:  str | None = Query(default=None),
    fault:       str | None = Query(default=None),
) -> HTMLResponse:
    """Handle SP-initiated SSO via GET (redirect binding detection + form render)."""
    return await _handle_sso(
        saml_request=SAMLRequest,
        relay_state=RelayState,
        fault=fault,
    )


@router.post("/saml/sso", response_class=HTMLResponse)
async def sso_post(
    SAMLRequest: str | None = Form(default=None),
    RelayState:  str | None = Form(default=None),
    fault:       str | None = Form(default=None),
) -> HTMLResponse:
    """Handle SP-initiated SSO via POST binding."""
    return await _handle_sso(
        saml_request=SAMLRequest,
        relay_state=RelayState,
        fault=fault,
    )


async def _handle_sso(
    saml_request: str | None,
    relay_state:  str | None,
    fault:        str | None,
) -> HTMLResponse:
    """
    Core SSO handler for both GET and POST:
      1. Parse the incoming SAMLRequest (if any) to extract InResponseTo ID
      2. Build + sign the SAMLResponse
      3. Render an auto-submitting HTML form POSTing to the ACS URL
    """
    config = saml_idp.load_config()

    if not config.get("cert_pem"):
        config = saml_idp.generate_certificate()
        log.info("Auto-generated SAML certificate during SSO flow")

    # Extract InResponseTo from the AuthnRequest if present
    in_response_to: str | None = None
    authn_request_xml: str | None = None
    if saml_request:
        try:
            # SAML AuthnRequest via HTTP-Redirect is deflated+base64; via POST just base64
            decoded = base64.b64decode(saml_request)
            try:
                import zlib
                decoded = zlib.decompress(decoded, -15)  # raw deflate
            except Exception:
                pass  # POST binding is not deflated
            authn_request_xml = decoded.decode("utf-8", errors="replace")
            # Quick text-search for ID attribute — avoid full XML parse dependency
            import re
            m = re.search(r'\bID=["\']([^"\']+)["\']', authn_request_xml)
            if m:
                in_response_to = m.group(1)
        except Exception as exc:
            log.warning("Could not parse SAMLRequest: %s", exc)

    # fault=bad_acs: use a deliberately wrong ACS URL
    effective_config = dict(config)
    if fault == "bad_acs":
        effective_config["acs_url"] = "https://lucid.app/saml/sso/WRONG-ACS-URL-INJECTED"

    acs_url = effective_config.get("acs_url", "")
    if not acs_url:
        return HTMLResponse(
            content=_error_page(
                "ACS URL not configured",
                "Set the ACS URL in the SAML IdP Setup panel before triggering SSO.",
            ),
            status_code=400,
        )

    # Build the full SAML response
    saml_response_b64, pretty_xml, step_data = saml_idp.build_full_saml_response(
        config=effective_config,
        in_response_to=in_response_to,
        fault=fault,
    )

    # Store for narrative
    global _last_saml_execution
    _last_saml_execution = {
        "acs_url":            acs_url,
        "idp_entity_id":      config.get("idp_entity_id"),
        "sp_entity_id":       config.get("sp_entity_id"),
        "fault":              fault,
        "fault_description":  step_data.get("fault_description", ""),
        "name_id":            step_data.get("name_id"),
        "email":              step_data.get("email"),
        "not_on_or_after":    step_data.get("not_on_or_after"),
        "authn_request_xml":  authn_request_xml,
        "pretty_xml":         pretty_xml[:2000],  # truncate for storage
        "step_data":          step_data,
    }

    # Render the auto-submit form — the browser will POST it immediately
    html = _auto_submit_form(
        acs_url=acs_url,
        saml_response_b64=saml_response_b64,
        relay_state=relay_state,
        pretty_xml=pretty_xml,
        step_data=step_data,
        fault=fault,
    )
    return HTMLResponse(content=html)


# ── GET /api/saml/config ────────────────────────────────────────────────────────

@router.get("/api/saml/config")
async def get_saml_config() -> JSONResponse:
    """
    Return current SAML IdP config.
    The private key is NEVER returned — only public/config values.
    """
    config = saml_idp.load_config()
    safe = {k: v for k, v in config.items() if k != "key_pem"}
    return JSONResponse(safe)


# ── POST /api/saml/config ───────────────────────────────────────────────────────

@router.post("/api/saml/config")
async def update_saml_config(request: Request) -> JSONResponse:
    """
    Update SP-side config fields.
    Accepts a JSON body with any subset of the config keys.
    Immutable fields (cert_pem, key_pem, idp_entity_id, idp_sso_url) are
    ignored if sent — the client cannot overwrite the cert via this endpoint.
    """
    body = await request.json()

    # Fields the client is allowed to set
    allowed = {
        "sp_entity_id", "acs_url",
        "attr_email", "attr_first_name", "attr_last_name", "name_id",
        "validity_minutes",
    }
    updates = {k: v for k, v in body.items() if k in allowed}
    updated = saml_idp.update_config(updates)
    safe = {k: v for k, v in updated.items() if k != "key_pem"}
    return JSONResponse(safe)


# ── POST /api/saml/generate-cert ───────────────────────────────────────────────

@router.post("/api/saml/generate-cert")
async def generate_cert() -> JSONResponse:
    """
    Regenerate the RSA keypair and self-signed X.509 certificate.
    After calling this, the new certificate must be re-registered in Lucid's
    admin panel — any existing SAML sessions will be unaffected but new logins
    will fail until the cert is updated.
    """
    config = saml_idp.generate_certificate()
    safe = {k: v for k, v in config.items() if k != "key_pem"}
    log.info("SAML certificate regenerated")
    return JSONResponse({
        "status": "ok",
        "message": "New certificate generated. Update it in Lucid's SAML admin panel.",
        "config": safe,
    })


# ── POST /api/saml/test-assertion ───────────────────────────────────────────────

@router.post("/api/saml/test-assertion")
async def test_assertion(request: Request) -> JSONResponse:
    """
    Generate a SAMLResponse without POSTing it to Lucid (dry-run mode).
    Returns the base64 payload, decoded pretty XML, and step metadata.
    Used by the educational UI to show what would be sent.

    Accepts optional JSON body:
      { "fault": "expired" | "wrong_cert" | "missing_email" | "wrong_issuer" | "bad_acs" }
    """
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    fault = body.get("fault") or None
    config = saml_idp.load_config()

    if not config.get("cert_pem"):
        config = saml_idp.generate_certificate()

    saml_response_b64, pretty_xml, step_data = saml_idp.build_full_saml_response(
        config=config,
        in_response_to=None,
        fault=fault,
    )

    return JSONResponse({
        "saml_response_b64": saml_response_b64,
        "pretty_xml":        pretty_xml,
        "step_data":         step_data,
        "acs_url":           config.get("acs_url", ""),
        "encoded_length":    len(saml_response_b64),
    })


# ── GET /api/saml/narrative ────────────────────────────────────────────────────

@router.get("/api/saml/narrative")
async def saml_narrative() -> JSONResponse:
    """Ask Claude to narrate the most recent SAML flow."""
    if not _last_saml_execution:
        return JSONResponse({"narrative": "No SAML flow has been executed yet. Trigger SSO first."})
    narrative = await generate_saml_narrative(_last_saml_execution)
    return JSONResponse({"narrative": narrative})


# ── HTML helpers ────────────────────────────────────────────────────────────────

def _auto_submit_form(
    acs_url: str,
    saml_response_b64: str,
    relay_state: str | None,
    pretty_xml: str,
    step_data: dict,
    fault: str | None,
) -> str:
    """
    Return an HTML page that:
      1. Shows the decoded SAML XML and step metadata (educational layer)
      2. Provides a "Send to Lucid →" button that submits the form
      3. Has a countdown that auto-submits after 5 seconds (skippable)

    The page is intentionally styled to match the app's dark IDE aesthetic.
    """
    relay_input = f'<input type="hidden" name="RelayState" value="{_esc(relay_state)}" />' if relay_state else ""

    fault_banner = ""
    if fault:
        fault_desc = step_data.get("fault_description", "")
        fault_banner = f"""
        <div class="fault-banner">
          <span class="fault-icon">⚠</span>
          <strong>Fault injected: {_esc(fault)}</strong><br>
          {_esc(fault_desc)}
        </div>"""

    # Annotated field table
    fields = [
        ("NameID",         step_data.get("name_id", ""),         "The unique identifier for the user — Lucid uses this to match the assertion to an account."),
        ("Issuer",         step_data.get("issuer", ""),          "The IdP entity ID — Lucid checks this against the registered IdP to verify it knows this sender."),
        ("NotBefore",      step_data.get("not_before", ""),      "The assertion is not valid before this timestamp. Clock skew between IdP and SP can cause failures here."),
        ("NotOnOrAfter",   step_data.get("not_on_or_after", ""), "The assertion expires at this timestamp. Lucid will reject assertions past this time."),
        ("ACS Recipient",  step_data.get("acs_url", ""),         "The URL this assertion is addressed to. Lucid verifies it matches the registered ACS URL."),
        ("SP Entity ID",   step_data.get("sp_entity_id", ""),    "The audience this assertion is for. Lucid checks it matches its own entity ID."),
        ("User.email",     step_data.get("email", ""),           "Required attribute — Lucid maps this to a user account. Missing = login failure."),
        ("User.FirstName", step_data.get("first_name", ""),      "Display name attribute — used to populate the user's profile."),
        ("User.LastName",  step_data.get("last_name", ""),       "Display name attribute — used to populate the user's profile."),
    ]

    rows = ""
    for label, value, annotation in fields:
        highlight = ' class="field-fault"' if (not value or value.startswith("(omitted")) else ""
        rows += f"""
        <tr{highlight}>
          <td class="field-label">{_esc(label)}</td>
          <td class="field-value">{_esc(str(value))}</td>
          <td class="field-annotation">{_esc(annotation)}</td>
        </tr>"""

    import html as html_module
    xml_escaped = html_module.escape(pretty_xml[:6000])  # cap for display

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>SAML Response — Lucid API Explorer IdP</title>
  <style>
    :root {{
      --bg: #0D1117; --surface: #161B22; --panel: #1E2A3A;
      --border: #2A3A4A; --green: #00FF88; --amber: #F0A500;
      --red: #FF6B6B; --blue: #7EB8F7; --text: #E8E8E8;
      --muted: #888; --mono: 'JetBrains Mono', monospace;
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{ background: var(--bg); color: var(--text); font-family: var(--mono); font-size: 13px; padding: 24px; }}
    h1 {{ font-size: 16px; color: var(--green); margin-bottom: 4px; }}
    .subtitle {{ color: var(--muted); font-size: 11px; margin-bottom: 20px; }}
    .fault-banner {{ background: color-mix(in srgb, var(--red) 15%, var(--panel));
      border: 1px solid var(--red); border-radius: 6px; padding: 12px 16px;
      margin-bottom: 16px; color: var(--red); line-height: 1.6; }}
    .fault-icon {{ margin-right: 6px; }}
    .section-label {{ font-size: 10px; font-weight: 700; color: var(--muted);
      letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 8px; }}
    table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
    th {{ font-size: 10px; color: var(--muted); text-align: left; padding: 4px 8px;
      border-bottom: 1px solid var(--border); text-transform: uppercase; letter-spacing: 0.1em; }}
    td {{ padding: 6px 8px; border-bottom: 1px solid var(--border); vertical-align: top; }}
    .field-label {{ color: var(--blue); min-width: 130px; white-space: nowrap; }}
    .field-value {{ color: var(--text); word-break: break-all; max-width: 280px; }}
    .field-annotation {{ color: var(--muted); font-size: 11px; }}
    tr.field-fault td {{ background: color-mix(in srgb, var(--red) 8%, transparent); }}
    tr.field-fault .field-label {{ color: var(--red); }}
    tr.field-fault .field-value {{ color: var(--red); }}
    .xml-block {{ background: var(--panel); border: 1px solid var(--border); border-radius: 6px;
      padding: 14px; overflow-x: auto; max-height: 300px; overflow-y: auto;
      font-size: 11px; color: var(--text); white-space: pre; line-height: 1.5; margin-bottom: 20px; }}
    .actions {{ display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
    .btn-submit {{ background: var(--blue); color: #000; font-family: var(--mono);
      font-size: 13px; font-weight: 700; border: none; border-radius: 5px;
      padding: 10px 24px; cursor: pointer; transition: opacity 0.15s; }}
    .btn-submit:hover {{ opacity: 0.85; }}
    .btn-cancel {{ background: none; border: 1px solid var(--border); color: var(--muted);
      font-family: var(--mono); font-size: 12px; border-radius: 5px;
      padding: 10px 16px; cursor: pointer; }}
    .countdown {{ color: var(--muted); font-size: 12px; }}
    #countdown-num {{ color: var(--amber); }}
    .back-link {{ display: inline-block; margin-bottom: 20px; color: var(--muted);
      text-decoration: none; font-size: 12px; }}
    .back-link:hover {{ color: var(--blue); }}
    .acs-target {{ color: var(--muted); font-size: 11px; margin-top: 8px; word-break: break-all; }}
  </style>
</head>
<body>

  <a href="/" class="back-link">← Back to Lucid API Explorer</a>

  <h1>✦ SAML Response Generated</h1>
  <p class="subtitle">Step 4 of 6 — Assertion signed, ready to POST to Lucid's ACS endpoint.</p>

  {fault_banner}

  <div class="section-label">Assertion Fields</div>
  <table>
    <thead><tr>
      <th>Field</th><th>Value</th><th>What it means</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table>

  <div class="section-label">Raw SAMLResponse XML (decoded)</div>
  <div class="xml-block">{xml_escaped}</div>

  <form method="POST" action="{_esc(acs_url)}" id="saml-form">
    <input type="hidden" name="SAMLResponse" value="{_esc(saml_response_b64)}" />
    {relay_input}

    <div class="actions">
      <button type="submit" class="btn-submit">Send to Lucid ACS →</button>
      <button type="button" class="btn-cancel" onclick="clearInterval(window._cd); document.getElementById('countdown-wrap').style.display='none'">
        Stop auto-send
      </button>
      <span class="countdown" id="countdown-wrap">
        Auto-sending in <span id="countdown-num">5</span>s…
      </span>
    </div>
    <p class="acs-target">Target ACS URL: {_esc(acs_url)}</p>
  </form>

  <script>
    var n = 5;
    window._cd = setInterval(function() {{
      n--;
      var el = document.getElementById('countdown-num');
      if (el) el.textContent = n;
      if (n <= 0) {{
        clearInterval(window._cd);
        document.getElementById('saml-form').submit();
      }}
    }}, 1000);
  </script>

</body>
</html>"""


def _error_page(title: str, detail: str) -> str:
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>SAML Error</title>
<style>body{{background:#0D1117;color:#E8E8E8;font-family:monospace;padding:32px}}
h1{{color:#FF6B6B}}p{{color:#888;margin-top:8px}}a{{color:#7EB8F7}}</style></head>
<body><h1>⚠ SAML Error: {_esc(title)}</h1><p>{_esc(detail)}</p>
<p><a href="/">← Back to Lucid API Explorer</a></p></body></html>"""


def _esc(s: object) -> str:
    """HTML-escape a value for safe attribute / text embedding."""
    import html
    return html.escape(str(s or ""), quote=True)
