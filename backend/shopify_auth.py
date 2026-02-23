"""
Shopify OAuth: install flow and token storage.
Store owner connects via /connect -> redirect to Shopify -> callback -> store token.
"""
import hashlib
import hmac
import json
import secrets
import re
from pathlib import Path
from urllib.parse import urlencode

import httpx

_project_root = Path(__file__).resolve().parent.parent
STORES_FILE = _project_root / "data" / "stores.json"
SCOPES = "read_orders"

# In-memory: state (nonce) -> shop domain (for callback verification)
_oauth_states: dict[str, str] = {}


def _ensure_stores_file() -> Path:
    STORES_FILE.parent.mkdir(parents=True, exist_ok=True)
    if not STORES_FILE.exists():
        STORES_FILE.write_text("{}")
    return STORES_FILE


def get_stored_shops() -> dict[str, str]:
    """Return { shop_domain: access_token }."""
    _ensure_stores_file()
    return json.loads(STORES_FILE.read_text())


def save_token(shop: str, access_token: str) -> None:
    """Persist access token for shop."""
    data = get_stored_shops()
    data[shop] = access_token
    _ensure_stores_file()
    STORES_FILE.write_text(json.dumps(data, indent=2))


def get_token(shop: str) -> str | None:
    """Return stored access token for shop, or None."""
    return get_stored_shops().get(normalize_shop(shop))


def normalize_shop(shop: str) -> str:
    """Return shop in form xxx.myshopify.com."""
    s = shop.strip().lower()
    if not s:
        return ""
    if ".myshopify.com" in s:
        return s.split(".myshopify.com")[0].split("//")[-1].rstrip("/") + ".myshopify.com"
    return s + ".myshopify.com"


def is_valid_shop_hostname(shop: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*\.myshopify\.com$", shop))


def verify_hmac(query_params: dict, secret: str) -> bool:
    """Verify Shopify HMAC. Build message from all params except hmac (sorted)."""
    if "hmac" not in query_params:
        return False
    received = query_params.get("hmac")
    rest = {k: v for k, v in query_params.items() if k != "hmac"}
    message = "&".join(f"{k}={v}" for k, v in sorted(rest.items()))
    expected = hmac.new(secret.encode(), message.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, received)


def build_authorize_url(shop: str, client_id: str, redirect_uri: str) -> tuple[str, str]:
    """Build Shopify OAuth authorize URL and state (nonce). Returns (url, state)."""
    redirect_uri = redirect_uri.rstrip("/")  # Shopify requires exact match; no trailing slash
    state = secrets.token_hex(16)
    _oauth_states[state] = shop
    params = {
        "client_id": client_id,
        "scope": SCOPES,
        "redirect_uri": redirect_uri,
        "state": state,
    }
    return f"https://{shop}/admin/oauth/authorize?{urlencode(params)}", state


def exchange_code_for_token(shop: str, code: str, client_id: str, client_secret: str) -> str:
    """POST to shop's oauth/access_token; return access_token."""
    url = f"https://{shop}/admin/oauth/access_token"
    with httpx.Client() as client:
        r = client.post(
            url,
            json={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
            },
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        r.raise_for_status()
        data = r.json()
    return data["access_token"]
