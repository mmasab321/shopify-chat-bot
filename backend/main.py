"""
Customer service chat backend. For now: generic chat with DeepSeek.
Later: Shopify OAuth + order lookup, then inject order context into the prompt.
"""
import os
from pathlib import Path

# Load .env from project root (parent of backend/) so it works regardless of cwd
_project_root = Path(__file__).resolve().parent.parent
_env_file = _project_root / ".env"

from dotenv import load_dotenv
load_dotenv(_env_file)

os.environ.setdefault("NO_PROXY", "*")

from fastapi import FastAPI, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from openai import OpenAI

import re
from backend import shopify_auth, shopify_api
from backend.shopify_config import (
    SHOPIFY_CLIENT_ID,
    SHOPIFY_CLIENT_SECRET,
    SHOPIFY_APP_URL,
    SHOPIFY_REDIRECT_URI,
    log_oauth_config,
)

# Log OAuth config at startup for debugging
log_oauth_config()

DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

app = FastAPI(title="Shopify Customer Chat")

# Allow tunnel origins (ngrok, Cloudflare quick tunnels) so chat works when opened via tunnel URL
_tunnel_origins = [
    "http://localhost:3000", "http://127.0.0.1:3000",
    "http://localhost:5500", "http://127.0.0.1:5500",
    "http://localhost:8000", "http://127.0.0.1:8000",
]
if SHOPIFY_APP_URL and SHOPIFY_APP_URL.startswith("https://"):
    _tunnel_origins.append(SHOPIFY_APP_URL.rstrip("/"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=_tunnel_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] | None = None


class ChatResponse(BaseModel):
    reply: str


def get_deepseek_reply(
    message: str,
    history: list[dict] | None = None,
    store_context: str | None = None,
    order_context: str | None = None,
) -> str:
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY not set in .env")

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    system = (
        "You are a friendly customer service assistant for an ecommerce store. "
        "Answer helpfully and concisely using ONLY the store data provided below. "
        "Do not invent product names, prices, or order details."
    )
    if store_context:
        system += f"\n\n[Current store data]\n{store_context}"
    if order_context:
        system += f"\n\n[Order lookup result]\n{order_context}"
    if not store_context and not order_context:
        system += " No store data is available yet; suggest they connect their store or ask for order number and email to look up an order."
    messages = [{"role": "system", "content": system}]
    if history:
        for h in history[-20:]:  # last 20 turns
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    completion = client.chat.completions.create(
        model=DEEPSEEK_MODEL,
        messages=messages,
        temperature=0.4,
    )
    return (completion.choices[0].message.content or "").strip()


@app.get("/health")
def health():
    """Tunnel/origin check: if this returns 200, the app is reachable at this host."""
    return {"ok": True, "app": "shopify-chat-bot"}


def _parse_order_lookup(message: str) -> tuple[str | None, str | None]:
    """Try to extract order number and email from message. Returns (order_number, email) or (None, None)."""
    # Simple patterns: "order #1234" / "order 1234", email-like substring
    email_re = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    order_re = r"(?:order\s*#?\s*|#)(\d+)"
    email_match = re.search(email_re, message)
    order_match = re.search(order_re, message, re.I)
    email = email_match.group(0).strip() if email_match else None
    order_num = order_match.group(1).strip() if order_match else None
    return (order_num, email)


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        history = [{"role": m.role, "content": m.content} for m in (req.history or [])]
        store_context = None
        order_context = None
        shops = shopify_auth.get_stored_shops()
        if shops:
            shop = next(iter(shops))
            token = shops[shop]
            store_context = shopify_api.build_store_context(shop, token)
            order_num, email = _parse_order_lookup(req.message)
            if order_num or email:
                order_context = shopify_api.build_order_context(shop, token, order_num or "", email or "")
                if not order_context:
                    order_context = "No order found for that order number and email."
        reply = get_deepseek_reply(req.message, history, store_context=store_context, order_context=order_context or None)
        return ChatResponse(reply=reply)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Chat failed: {e}")


# --- Shopify connect (OAuth) ---

@app.get("/auth/shopify")
def auth_shopify_start(shop: str = Query(..., alias="shop")):
    """Redirect store owner to Shopify OAuth. shop = mystore.myshopify.com or mystore (full URL ok)."""
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Shopify app not configured. Set SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET, and SHOPIFY_APP_URL in .env, then restart the server.")
    normalized = shopify_auth.normalize_shop(shop)
    if not shopify_auth.is_valid_shop_hostname(normalized):
        raise HTTPException(status_code=400, detail="Invalid shop. Use your-store.myshopify.com or your-store.")
    # All auth URLs from single config; redirect_uri derived from SHOPIFY_APP_URL
    log_oauth_config()
    url, _ = shopify_auth.build_authorize_url(normalized, SHOPIFY_CLIENT_ID, SHOPIFY_REDIRECT_URI)
    # Debug: log exact redirect_uri we're sending so it can be copy-pasted into Shopify dashboard
    import sys
    print(f"[Shopify OAuth] redirect_uri sent to Shopify: {repr(SHOPIFY_REDIRECT_URI)}", file=sys.stderr)
    return RedirectResponse(url=url, status_code=302)


@app.get("/auth/shopify/callback")
def auth_shopify_callback(request: Request):
    """Shopify redirects here after approval. Verify HMAC and state, exchange code, save token."""
    if not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail="Shopify app not configured.")
    params = dict(request.query_params)
    raw_query = request.scope.get("query_string", b"").decode("utf-8")
    ok = shopify_auth.verify_hmac_raw_query(raw_query, SHOPIFY_CLIENT_SECRET) or shopify_auth.verify_hmac(params, SHOPIFY_CLIENT_SECRET)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid HMAC")
    state = params.get("state")
    shop = shopify_auth._oauth_states.pop(state, None)
    incoming_shop = shopify_auth.normalize_shop(params.get("shop", ""))
    if not shop or shop != incoming_shop:
        raise HTTPException(status_code=400, detail="Invalid or expired state. Try connecting again.")
    code = params.get("code")
    if not code:
        raise HTTPException(status_code=400, detail="Missing code")
    try:
        token = shopify_auth.exchange_code_for_token(shop, code, SHOPIFY_CLIENT_ID, SHOPIFY_CLIENT_SECRET)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not get token: {e}")
    shopify_auth.save_token(shop, token)
    return RedirectResponse(url="/connect?connected=1", status_code=302)


@app.get("/api/connected_shops")
def api_connected_shops():
    """Return list of connected shop domains (for the chat UI)."""
    shops = list(shopify_auth.get_stored_shops().keys())
    return {"shops": shops}


class DisconnectRequest(BaseModel):
    shop: str


@app.post("/api/disconnect")
def api_disconnect(req: DisconnectRequest):
    """Remove a store from connected shops (disconnect)."""
    normalized = shopify_auth.normalize_shop(req.shop)
    if not shopify_auth.remove_shop(normalized):
        raise HTTPException(status_code=404, detail="Store not found or not connected.")
    return {"ok": True, "shop": normalized}


# Show exact redirect URI and sample authorize URL for debugging
@app.get("/api/shopify_redirect_uri")
def shopify_redirect_uri():
    return {"redirect_uri": SHOPIFY_REDIRECT_URI, "app_url": SHOPIFY_APP_URL, "client_id": SHOPIFY_CLIENT_ID or "(not set)"}


@app.get("/api/shopify_debug")
def shopify_debug():
    """Exact URL we would use for OAuth (with a placeholder shop). Use this to verify what Shopify receives."""
    from urllib.parse import urlencode
    shop = "your-store.myshopify.com"
    params = {"client_id": SHOPIFY_CLIENT_ID or "", "scope": "read_orders", "redirect_uri": SHOPIFY_REDIRECT_URI, "state": "debug"}
    url = f"https://{shop}/admin/oauth/authorize?{urlencode(params)}"
    return {"redirect_uri": SHOPIFY_REDIRECT_URI, "app_url": SHOPIFY_APP_URL, "authorize_url_example": url}


# Connect page (store owner links their Shopify store)
@app.get("/connect")
def connect_page():
    connect_path = Path(__file__).resolve().parent.parent / "static" / "connect.html"
    if connect_path.exists():
        return FileResponse(connect_path)
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="<h1>Connect your Shopify store</h1><p><a href='/'>Back to chat</a></p><p>Add static/connect.html for the form.</p>")


# Serve frontend
STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
