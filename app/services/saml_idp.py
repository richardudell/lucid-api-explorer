"""
app/services/saml_idp.py — SAML 2.0 Identity Provider service layer.

Responsibilities:
  - Generate and persist self-signed RSA keypairs + X.509 certificates
  - Load / save IdP configuration to saml_config.json (survives restarts)
  - Build well-formed SAML 2.0 AuthnResponse XML with all required elements
  - Sign the Assertion element with RSA-SHA256 / XMLDSig enveloped signature
  - Produce IdP metadata XML (what you paste into Lucid's admin panel)
  - Support fault-injection modes for educational "break it" demonstrations

SAML profile implemented:
  Web Browser SSO — HTTP-POST binding (SP-initiated and IdP-initiated)
  Assertion signed, Response unsigned (most common real-world config)
  NameID format: urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress
  Attributes: User.email, User.FirstName, User.LastName (Lucid's expected names)

Persistence:
  saml_config.json lives at the project root.
  It holds the PEM cert, PEM private key, entity IDs, ACS URL, and
  attribute values. Gitignored — never committed.
"""

import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from lxml import etree
from signxml import XMLSigner, methods

log = logging.getLogger(__name__)

# ── Config file path ────────────────────────────────────────────────────────────
# Sits next to main.py at the project root.
_CONFIG_PATH = Path(__file__).parent.parent.parent / "saml_config.json"

# ── SAML XML namespaces ─────────────────────────────────────────────────────────
_NS = {
    "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
    "saml":  "urn:oasis:names:tc:SAML:2.0:assertion",
    "ds":    "http://www.w3.org/2000/09/xmldsig#",
}

# ── Default IdP configuration ───────────────────────────────────────────────────
_DEFAULTS: dict[str, Any] = {
    # IdP-side (this app) — auto-populated, user doesn't change these
    "idp_entity_id":   "http://localhost:8000/saml/metadata",
    "idp_sso_url":     "http://localhost:8000/saml/sso",
    "cert_pem":        "",   # filled on first generate_certificate() call
    "key_pem":         "",   # filled on first generate_certificate() call
    "cert_fingerprint": "",  # SHA-256 fingerprint for quick display
    "cert_subject":    "",   # human-readable cert subject
    "cert_not_after":  "",   # ISO-8601 expiry

    # SP-side (Lucid) — user fills these in from Lucid's admin panel
    "sp_entity_id": "",
    "acs_url":      "",

    # Attributes sent in the assertion — default values the user can override
    "attr_email":      "testuser@example.com",
    "attr_first_name": "Test",
    "attr_last_name":  "User",
    "name_id":         "testuser@example.com",

    # Assertion validity window (minutes)
    "validity_minutes": 10,
}


# ── Config persistence ──────────────────────────────────────────────────────────

def load_config() -> dict[str, Any]:
    """
    Load IdP config from saml_config.json.
    Returns defaults merged with whatever is stored on disk.
    If the file doesn't exist yet, returns defaults (no cert yet).
    """
    config = dict(_DEFAULTS)
    if _CONFIG_PATH.exists():
        try:
            stored = json.loads(_CONFIG_PATH.read_text())
            config.update(stored)
        except Exception as exc:
            log.warning("saml_config.json unreadable (%s) — using defaults", exc)
    return config


def save_config(config: dict[str, Any]) -> None:
    """Persist config to saml_config.json (pretty-printed for readability)."""
    payload = json.dumps(config, indent=2)
    fd = os.open(_CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(payload)
    try:
        os.chmod(_CONFIG_PATH, 0o600)
    except OSError:
        # Best effort on platforms/filesystems that ignore chmod semantics.
        pass
    log.info("SAML config saved to %s", _CONFIG_PATH)


def update_config(updates: dict[str, Any]) -> dict[str, Any]:
    """
    Merge updates into the current config and save.
    Returns the full updated config.
    """
    config = load_config()
    config.update(updates)
    save_config(config)
    return config


# ── Certificate generation ──────────────────────────────────────────────────────

def generate_certificate() -> dict[str, Any]:
    """
    Generate a new 2048-bit RSA private key and a self-signed X.509 certificate.
    Saves both (PEM-encoded) into saml_config.json and returns the updated config.

    The cert is valid for 10 years — appropriate for a dev/test IdP.
    Subject CN is set to the IdP entity ID so it's recognisable in Lucid's UI.
    """
    config = load_config()

    # 1. Generate private key
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # 2. Build a minimal self-signed cert
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Lucid API Explorer IdP"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Lucid API Explorer"),
    ])

    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=3650))  # 10 years
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(private_key, hashes.SHA256())
    )

    # 3. Serialize to PEM
    key_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()

    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()

    # 4. Compute fingerprint (SHA-256 hex, colon-separated — shown in UI)
    fp_bytes = cert.fingerprint(hashes.SHA256())
    fingerprint = ":".join(f"{b:02X}" for b in fp_bytes)

    not_after_iso = cert.not_valid_after_utc.isoformat()
    subject_str = cert.subject.rfc4514_string()

    # 5. Persist and return
    updates = {
        "cert_pem":        cert_pem,
        "key_pem":         key_pem,
        "cert_fingerprint": fingerprint,
        "cert_subject":    subject_str,
        "cert_not_after":  not_after_iso,
    }
    return update_config(updates)


def get_cert_for_metadata(config: dict[str, Any]) -> str:
    """
    Return the base64-encoded DER form of the certificate, suitable for
    embedding in IdP metadata XML inside <ds:X509Certificate>.
    Strips PEM headers and all newlines.
    """
    pem = config.get("cert_pem", "")
    lines = [l for l in pem.splitlines() if not l.startswith("-----")]
    return "".join(lines)


# ── SAML XML builders ───────────────────────────────────────────────────────────

def _uid() -> str:
    """Generate a SAML-safe unique ID (must start with a letter)."""
    return "_" + uuid.uuid4().hex


def _ts(dt: datetime) -> str:
    """Format a datetime as a SAML timestamp string."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def build_assertion_xml(
    config: dict[str, Any],
    in_response_to: str | None = None,
    fault: str | None = None,
) -> tuple[etree._Element, dict[str, Any]]:
    """
    Build a SAML 2.0 Assertion element (not yet signed).

    Args:
        config:          Current IdP config dict.
        in_response_to:  The ID from the SP's AuthnRequest, if SP-initiated.
        fault:           Optional fault injection key — one of:
                           'expired'        — NotOnOrAfter set 5 minutes in the past
                           'wrong_issuer'   — Issuer replaced with random string
                           'missing_email'  — User.email attribute omitted
                         (wrong_cert and bad_acs are handled at the route layer)

    Returns:
        (assertion_element, step_data) where step_data is a dict describing
        every field for the educational UI.
    """
    now = datetime.now(timezone.utc)
    validity_minutes = config.get("validity_minutes", 10)

    # Fault: expired assertion
    if fault == "expired":
        not_before    = now - timedelta(minutes=validity_minutes + 5)
        not_on_or_after = now - timedelta(minutes=5)  # already expired
    else:
        not_before    = now - timedelta(seconds=10)   # small skew buffer
        not_on_or_after = now + timedelta(minutes=validity_minutes)

    assertion_id = _uid()
    issuer_value = config.get("idp_entity_id", "http://localhost:8000/saml/metadata")

    # Fault: wrong issuer
    if fault == "wrong_issuer":
        issuer_value = "urn:unknown-idp-that-lucid-does-not-recognise"

    name_id_value = config.get("name_id", "testuser@example.com")
    sp_entity_id  = config.get("sp_entity_id", "")
    acs_url       = config.get("acs_url", "")

    # ── Assertion element ────────────────────────────────────────────────────────
    assertion = etree.Element(
        "{urn:oasis:names:tc:SAML:2.0:assertion}Assertion",
        nsmap={
            "saml":  "urn:oasis:names:tc:SAML:2.0:assertion",
            "xs":    "http://www.w3.org/2001/XMLSchema",
            "xsi":   "http://www.w3.org/2001/XMLSchema-instance",
        },
        attrib={
            "ID":           assertion_id,
            "Version":      "2.0",
            "IssueInstant": _ts(now),
        },
    )

    # Issuer
    issuer_el = etree.SubElement(
        assertion,
        "{urn:oasis:names:tc:SAML:2.0:assertion}Issuer",
    )
    issuer_el.text = issuer_value

    # Subject
    subject = etree.SubElement(assertion, "{urn:oasis:names:tc:SAML:2.0:assertion}Subject")
    name_id = etree.SubElement(
        subject,
        "{urn:oasis:names:tc:SAML:2.0:assertion}NameID",
        attrib={
            "Format": "urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress",
        },
    )
    name_id.text = name_id_value

    subj_conf = etree.SubElement(
        subject,
        "{urn:oasis:names:tc:SAML:2.0:assertion}SubjectConfirmation",
        attrib={"Method": "urn:oasis:names:tc:SAML:2.0:cm:bearer"},
    )
    scdata_attrib: dict[str, str] = {
        "NotOnOrAfter": _ts(not_on_or_after),
        "Recipient":    acs_url,
    }
    if in_response_to:
        scdata_attrib["InResponseTo"] = in_response_to
    etree.SubElement(
        subj_conf,
        "{urn:oasis:names:tc:SAML:2.0:assertion}SubjectConfirmationData",
        attrib=scdata_attrib,
    )

    # Conditions
    conditions = etree.SubElement(
        assertion,
        "{urn:oasis:names:tc:SAML:2.0:assertion}Conditions",
        attrib={
            "NotBefore":    _ts(not_before),
            "NotOnOrAfter": _ts(not_on_or_after),
        },
    )
    if sp_entity_id:
        audience_restriction = etree.SubElement(
            conditions,
            "{urn:oasis:names:tc:SAML:2.0:assertion}AudienceRestriction",
        )
        audience = etree.SubElement(
            audience_restriction,
            "{urn:oasis:names:tc:SAML:2.0:assertion}Audience",
        )
        audience.text = sp_entity_id

    # AuthnStatement
    authn_stmt = etree.SubElement(
        assertion,
        "{urn:oasis:names:tc:SAML:2.0:assertion}AuthnStatement",
        attrib={"AuthnInstant": _ts(now), "SessionIndex": _uid()},
    )
    authn_ctx = etree.SubElement(
        authn_stmt,
        "{urn:oasis:names:tc:SAML:2.0:assertion}AuthnContext",
    )
    authn_ctx_cls = etree.SubElement(
        authn_ctx,
        "{urn:oasis:names:tc:SAML:2.0:assertion}AuthnContextClassRef",
    )
    authn_ctx_cls.text = "urn:oasis:names:tc:SAML:2.0:ac:classes:PasswordProtectedTransport"

    # AttributeStatement
    attr_stmt = etree.SubElement(
        assertion,
        "{urn:oasis:names:tc:SAML:2.0:assertion}AttributeStatement",
    )

    def _add_attr(name: str, value: str) -> None:
        attr = etree.SubElement(
            attr_stmt,
            "{urn:oasis:names:tc:SAML:2.0:assertion}Attribute",
            attrib={
                "Name": name,
                "NameFormat": "urn:oasis:names:tc:SAML:2.0:attrname-format:basic",
            },
        )
        av = etree.SubElement(
            attr,
            "{urn:oasis:names:tc:SAML:2.0:assertion}AttributeValue",
            attrib={
                "{http://www.w3.org/2001/XMLSchema-instance}type": "xs:string",
            },
        )
        av.text = value

    # Fault: missing email
    if fault != "missing_email":
        _add_attr("User.email",     config.get("attr_email",      "testuser@example.com"))
    _add_attr("User.FirstName", config.get("attr_first_name", "Test"))
    _add_attr("User.LastName",  config.get("attr_last_name",  "User"))

    # Step data for educational UI
    step_data = {
        "assertion_id":    assertion_id,
        "issuer":          issuer_value,
        "name_id":         name_id_value,
        "not_before":      _ts(not_before),
        "not_on_or_after": _ts(not_on_or_after),
        "acs_url":         acs_url,
        "sp_entity_id":    sp_entity_id,
        "email":           config.get("attr_email",      "testuser@example.com") if fault != "missing_email" else "(omitted — fault injected)",
        "first_name":      config.get("attr_first_name", "Test"),
        "last_name":       config.get("attr_last_name",  "User"),
        "fault":           fault,
    }
    return assertion, step_data


def build_response_xml(
    config: dict[str, Any],
    signed_assertion: etree._Element,
    in_response_to: str | None = None,
    fault: str | None = None,
) -> etree._Element:
    """
    Wrap a (signed) Assertion inside a SAML Response envelope.

    The Response itself is not signed — only the Assertion is signed.
    This is the most common production pattern and what Lucid expects.
    """
    now = datetime.now(timezone.utc)
    response_id = _uid()
    acs_url    = config.get("acs_url", "")
    issuer_value = config.get("idp_entity_id", "http://localhost:8000/saml/metadata")

    response = etree.Element(
        "{urn:oasis:names:tc:SAML:2.0:protocol}Response",
        nsmap={
            "samlp": "urn:oasis:names:tc:SAML:2.0:protocol",
            "saml":  "urn:oasis:names:tc:SAML:2.0:assertion",
        },
        attrib={
            "ID":           response_id,
            "Version":      "2.0",
            "IssueInstant": _ts(now),
            "Destination":  acs_url,
        },
    )
    if in_response_to:
        response.set("InResponseTo", in_response_to)

    # Issuer
    issuer_el = etree.SubElement(
        response,
        "{urn:oasis:names:tc:SAML:2.0:assertion}Issuer",
    )
    issuer_el.text = issuer_value

    # Status (always Success for happy path — fault errors are still Success at
    # the Response level; Lucid validates the Assertion fields, not this element)
    status = etree.SubElement(response, "{urn:oasis:names:tc:SAML:2.0:protocol}Status")
    status_code = etree.SubElement(
        status,
        "{urn:oasis:names:tc:SAML:2.0:protocol}StatusCode",
        attrib={"Value": "urn:oasis:names:tc:SAML:2.0:status:Success"},
    )

    # Embed the signed assertion
    response.append(signed_assertion)

    return response


def sign_assertion(
    assertion: etree._Element,
    config: dict[str, Any],
    fault: str | None = None,
) -> etree._Element:
    """
    Sign the Assertion element using RSA-SHA256 with enveloped-signature transform.

    Args:
        assertion: The unsigned Assertion element.
        config:    Current config (holds key_pem and cert_pem).
        fault:     'wrong_cert' — sign with a freshly-generated throwaway key
                   so the signature is invalid against the registered cert.

    Returns:
        The signed Assertion element (modified in place by signxml, returned
        for clarity).
    """
    cert_pem = config.get("cert_pem", "").encode()
    key_pem  = config.get("key_pem",  "").encode()

    if fault == "wrong_cert":
        # Generate a throwaway keypair — signature will not verify against
        # the cert that Lucid has registered, causing a verification failure.
        wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        key_pem = wrong_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
        log.info("SAML fault: signing with throwaway key (wrong_cert)")

    signer = XMLSigner(
        method=methods.enveloped,
        signature_algorithm="rsa-sha256",
        digest_algorithm="sha256",
        c14n_algorithm="http://www.w3.org/2001/10/xml-exc-c14n#",
    )

    signed = signer.sign(
        assertion,
        key=key_pem,
        cert=cert_pem,
        reference_uri=assertion.get("ID"),
    )
    return signed


def encode_saml_response(response_element: etree._Element) -> str:
    """
    Serialize the Response element to XML bytes, then base64-encode it.
    This is the value that goes into the SAMLResponse POST form field.
    """
    xml_bytes = etree.tostring(
        response_element,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=False,
    )
    return base64.b64encode(xml_bytes).decode()


def decode_saml_response(b64: str) -> str:
    """
    Decode a base64 SAMLResponse back to pretty-printed XML.
    Used by the educational UI to show the decoded assertion.
    """
    xml_bytes = base64.b64decode(b64)
    root = etree.fromstring(xml_bytes)
    return etree.tostring(root, pretty_print=True, encoding="unicode")


def build_idp_metadata_xml(config: dict[str, Any]) -> str:
    """
    Build IdP metadata XML.

    This is the document you paste into Lucid's admin panel (or point Lucid at
    via the metadata URL). It declares:
      - The IdP entity ID
      - The SSO endpoint (HTTP-POST binding)
      - The signing certificate

    Returns pretty-printed XML as a string.
    """
    cert_b64 = get_cert_for_metadata(config)
    idp_entity_id = config.get("idp_entity_id", "http://localhost:8000/saml/metadata")
    sso_url = config.get("idp_sso_url", "http://localhost:8000/saml/sso")

    root = etree.Element(
        "EntityDescriptor",
        nsmap={
            None:  "urn:oasis:names:tc:SAML:2.0:metadata",
            "ds":  "http://www.w3.org/2000/09/xmldsig#",
        },
        attrib={"entityID": idp_entity_id},
    )

    idp_desc = etree.SubElement(root, "IDPSSODescriptor",
        attrib={
            "WantAuthnRequestsSigned": "false",
            "protocolSupportEnumeration": "urn:oasis:names:tc:SAML:2.0:protocol",
        })

    # Key descriptor (signing)
    key_desc = etree.SubElement(idp_desc, "KeyDescriptor", attrib={"use": "signing"})
    key_info = etree.SubElement(key_desc, "{http://www.w3.org/2000/09/xmldsig#}KeyInfo")
    x509data = etree.SubElement(key_info, "{http://www.w3.org/2000/09/xmldsig#}X509Data")
    x509cert = etree.SubElement(x509data, "{http://www.w3.org/2000/09/xmldsig#}X509Certificate")
    x509cert.text = cert_b64

    # SSO service (POST binding)
    etree.SubElement(
        idp_desc,
        "SingleSignOnService",
        attrib={
            "Binding":  "urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST",
            "Location": sso_url,
        },
    )

    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8").decode()


# ── High-level flow builder ─────────────────────────────────────────────────────

def build_full_saml_response(
    config: dict[str, Any],
    in_response_to: str | None = None,
    fault: str | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """
    End-to-end SAML response builder. Called by routes/saml.py.

    Builds the assertion, signs it, wraps in a Response, base64-encodes it.

    Args:
        config:          Current IdP config.
        in_response_to:  AuthnRequest ID from the SP, if available.
        fault:           Optional fault key for break-it mode.

    Returns:
        (saml_response_b64, pretty_xml, step_data)
        - saml_response_b64: the value for the SAMLResponse form field
        - pretty_xml:        human-readable decoded XML for the UI
        - step_data:         field-level metadata for annotation layer
    """
    assertion, step_data = build_assertion_xml(config, in_response_to=in_response_to, fault=fault)
    signed_assertion     = sign_assertion(assertion, config, fault=fault)
    response_element     = build_response_xml(config, signed_assertion, in_response_to=in_response_to, fault=fault)
    saml_response_b64    = encode_saml_response(response_element)
    pretty_xml           = etree.tostring(response_element, pretty_print=True, encoding="unicode")

    step_data["response_id"]       = response_element.get("ID")
    step_data["encoded_length"]    = len(saml_response_b64)
    step_data["fault_description"] = _fault_description(fault)

    return saml_response_b64, pretty_xml, step_data


def _fault_description(fault: str | None) -> str:
    """Return a human-readable description of what a fault injection does."""
    descriptions = {
        "expired":       "NotOnOrAfter was set 5 minutes in the past — Lucid will reject this as an expired assertion.",
        "wrong_cert":    "The assertion was signed with a different private key than the cert Lucid has registered — signature verification will fail.",
        "missing_email": "The User.email attribute was omitted — Lucid requires this attribute to map the assertion to a user account.",
        "wrong_issuer":  "The Issuer was set to an unknown entity ID — Lucid will not recognise this IdP.",
        "bad_acs":       "The SAMLResponse will be POSTed to a deliberately wrong ACS URL — Lucid will never receive it.",
    }
    return descriptions.get(fault or "", "")


# ── Ensure cert exists on import ────────────────────────────────────────────────
# If no config file exists yet, we can't auto-generate because we don't want
# side effects at import time. The /api/saml/generate-cert endpoint handles it.
# But if config exists without a cert (e.g. someone cleared it), we log a warning.

def _check_cert_on_startup() -> None:
    if _CONFIG_PATH.exists():
        try:
            os.chmod(_CONFIG_PATH, 0o600)
        except OSError:
            pass
        cfg = load_config()
        if not cfg.get("cert_pem"):
            log.warning(
                "saml_config.json exists but has no certificate. "
                "Call POST /api/saml/generate-cert to generate one."
            )


_check_cert_on_startup()
