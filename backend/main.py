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

from backend import shopify_auth
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


def get_deepseek_reply(message: str, history: list[dict] | None = None) -> str:
    if not DEEPSEEK_API_KEY:
        raise ValueError("DEEPSEEK_API_KEY not set in .env")

    client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
    system = (
        "You are a friendly customer service assistant for an ecommerce store. "
        "Answer helpfully and concisely. If the user asks about orders, refunds, or shipping, "
        "say you'll need to look up their order (they can share order number and email when we connect the store). "
        "For now, keep the tone warm and professional."
    )
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


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    try:
        history = [{"role": m.role, "content": m.content} for m in (req.history or [])]
        reply = get_deepseek_reply(req.message, history)
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
    if not shopify_auth.verify_hmac(dict(params), SHOPIFY_CLIENT_SECRET):
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
