"""
Single source of truth for Shopify OAuth configuration.
All auth URLs and credentials are derived from env; redirect_uri is built from SHOPIFY_APP_URL.
"""
import os
import sys
from pathlib import Path

# Load .env from project root so config is available when this module is imported
_root = Path(__file__).resolve().parent.parent
_env = _root / ".env"
if _env.exists():
    from dotenv import load_dotenv
    load_dotenv(_env)

# Preferred env names; fallback to legacy names for backward compatibility
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID") or os.getenv("SHOPIFY_API_KEY")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET") or os.getenv("SHOPIFY_API_SECRET")

# Base URL of this app (no trailing slash). Must match App URL in Shopify dashboard.
_raw_app_url = (os.getenv("SHOPIFY_APP_URL", "http://localhost:8000") or "").strip().rstrip("/")
SHOPIFY_APP_URL = _raw_app_url or "http://localhost:8000"

# redirect_uri is ALWAYS derived from SHOPIFY_APP_URL (never hardcoded or from a separate env).
SHOPIFY_REDIRECT_URI = f"{SHOPIFY_APP_URL}/auth/shopify/callback"


def log_oauth_config() -> None:
    """Log final client_id and redirect_uri for debugging verification."""
    print("[Shopify OAuth config]", file=sys.stderr)
    print(f"  client_id: {SHOPIFY_CLIENT_ID or '(not set)'}", file=sys.stderr)
    print(f"  redirect_uri: {SHOPIFY_REDIRECT_URI}", file=sys.stderr)
    print(f"  app_url: {SHOPIFY_APP_URL}", file=sys.stderr)
