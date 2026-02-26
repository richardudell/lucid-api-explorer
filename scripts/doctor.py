#!/usr/bin/env python3
"""
scripts/doctor.py — Local onboarding preflight checks.

Usage:
  python scripts/doctor.py
  python scripts/doctor.py --demo

Checks:
  - Python version (expects 3.12.x)
  - .env presence and basic variable completeness
  - OAuth redirect URI sanity
  - Optional feature keys (SCIM / Anthropic)
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def parse_env(path: pathlib.Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'").strip('"')
    return values


def is_placeholder(value: str | None) -> bool:
    v = (value or "").strip()
    if not v:
        return True
    return v.endswith("_here") or v.startswith("your_") or v.startswith("__DEMO_")


def ok(label: str, detail: str = "") -> None:
    msg = f"[OK]   {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def warn(label: str, detail: str = "") -> None:
    msg = f"[WARN] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def fail(label: str, detail: str = "") -> None:
    msg = f"[FAIL] {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)


def valid_local_redirect(uri: str) -> bool:
    return bool(re.match(r"^https?://localhost:\d+/.+", uri or ""))


def main() -> int:
    parser = argparse.ArgumentParser(description="Lucid API Explorer setup doctor")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Use demo expectations (allows missing real secrets).",
    )
    args = parser.parse_args()

    print("Lucid API Explorer — Doctor")
    print(f"Workspace: {ROOT}")

    failures = 0

    # Python version check
    py = sys.version_info
    if (py.major, py.minor) == (3, 12):
        ok("Python version", f"{py.major}.{py.minor}.{py.micro}")
    else:
        failures += 1
        fail(
            "Python version",
            f"found {py.major}.{py.minor}.{py.micro}; expected 3.12.x",
        )

    # .env check
    if ENV_PATH.exists():
        ok(".env file found", str(ENV_PATH))
    else:
        failures += 1
        fail(".env file missing", "run: cp .env.example .env")
        env = {}
    env = parse_env(ENV_PATH)

    # OAuth config checks
    required_oauth = [
        "LUCID_CLIENT_ID",
        "LUCID_CLIENT_SECRET",
        "LUCID_REDIRECT_URI",
        "LUCID_ACCOUNT_REDIRECT_URI",
    ]
    for key in required_oauth:
        val = env.get(key)
        if is_placeholder(val):
            if args.demo:
                warn(key, "placeholder/missing (allowed in demo mode)")
            else:
                failures += 1
                fail(key, "missing or placeholder")
        else:
            ok(key)

    # Redirect URI sanity
    for key in ("LUCID_REDIRECT_URI", "LUCID_ACCOUNT_REDIRECT_URI"):
        val = env.get(key, "")
        if not val:
            continue
        if valid_local_redirect(val):
            ok(f"{key} format", val)
        else:
            warn(f"{key} format", f"unexpected value: {val}")

    # Optional feature keys
    scim = env.get("LUCID_SCIM_TOKEN", "")
    anthropic = env.get("ANTHROPIC_API_KEY", "")
    if is_placeholder(scim):
        warn("LUCID_SCIM_TOKEN", "SCIM features will be disabled/unauthed")
    else:
        ok("LUCID_SCIM_TOKEN")

    if is_placeholder(anthropic):
        warn("ANTHROPIC_API_KEY", "AI features (Narrative/Generate with Claude) will be disabled")
    else:
        ok("ANTHROPIC_API_KEY")

    # Recommended next step
    if failures:
        print("\nDoctor result: FAIL")
        print("Fix failures above, then rerun:")
        print("  python scripts/doctor.py")
        return 1

    print("\nDoctor result: PASS")
    print("Next:")
    print("  source .venv/bin/activate")
    print("  python main.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
