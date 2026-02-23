# Shopify customer support chat (localhost)

Chat UI + backend. **Connect your Shopify store** to link your shop; then we can add order lookup so the bot uses real order data.

## Run locally

```bash
cd shopify-chat-bot
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Start the server (serves API + chat page):

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Open in the browser: **http://localhost:8000**

## Connect your Shopify store

1. In the chat page, click **“Connect your store”** in the header (or open **http://localhost:8000/connect**).
2. Enter your store URL (e.g. `mystore.myshopify.com` or `mystore`) and click **Connect with Shopify**.
3. You’ll be sent to Shopify to approve the app; after approval you’re redirected back and the store is linked.

**Setup:** Create an app in the [Shopify Partners dashboard](https://partners.shopify.com), add **read_orders** scope. Set **App URL** to `http://localhost:8000` and **Redirect URLs** to `http://localhost:8000/auth/shopify/callback`. In `.env` set `SHOPIFY_APP_URL=http://localhost:8000`, `SHOPIFY_CLIENT_ID`, and `SHOPIFY_CLIENT_SECRET` (redirect_uri is derived from `SHOPIFY_APP_URL`).

**If you get “redirect_uri and application url must have matching hosts” on localhost:** The new dev dashboard can be strict. Use a tunnel so Shopify sees a single public host:

1. Install [ngrok](https://ngrok.com) (or run `brew install ngrok`).
2. Start your app: `uvicorn backend.main:app --host 0.0.0.0 --port 8000`.
3. In another terminal: `ngrok http 8000`. Copy the HTTPS URL (e.g. `https://abc123.ngrok-free.app`).
4. In your Shopify app’s **Versions** config set **App URL** to `https://abc123.ngrok-free.app` and **Redirect URLs** to `https://abc123.ngrok-free.app/auth/shopify/callback`.
5. In `.env` set `SHOPIFY_APP_URL=https://abc123.ngrok-free.app` (redirect_uri is derived automatically).
6. Restart uvicorn, then open the ngrok URL in the browser and use **Connect your store** from there.

## Deploy on Render (fixed URL, no tunnel)

Use a **Web Service**, not a Static Site (this app is a Python backend).

1. **Push the repo to GitHub** (if you haven’t already).

2. In [Render](https://dashboard.render.com): **New → Web Service** (not Static Site). Connect the `shopify-chat-bot` repo.

3. **Settings:**
   - **Build command:** `pip install -r requirements.txt`
   - **Start command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Environment:** Python 3

4. **Environment variables** (Render → Environment):
   - `DEEPSEEK_API_KEY` = your key  
   - `SHOPIFY_APP_URL` = **your Render URL** (e.g. `https://shopify-chat-bot-xyz.onrender.com`) — set this *after* the first deploy so you have the URL  
   - `SHOPIFY_CLIENT_ID` = from Shopify Partners  
   - `SHOPIFY_CLIENT_SECRET` = from Shopify Partners  

5. **After first deploy:** Copy the service URL (e.g. `https://shopify-chat-bot-xyz.onrender.com`). Set `SHOPIFY_APP_URL` to that in Render env, and in **Shopify app → Versions**: App URL = that URL, Redirect URLs = `https://your-service.onrender.com/auth/shopify/callback`. Redeploy if you had to add `SHOPIFY_APP_URL` later.

6. Open `https://your-service.onrender.com/connect` and connect your store.

**Note:** On the free tier, the service spins down when idle (first request can be slow). Stored tokens are in `data/stores.json` on the server; the disk is ephemeral, so a redeploy clears them (for production you’d store tokens in a DB).

---

## What’s included

- **Backend** (`backend/main.py`): Chat API, DeepSeek replies, Shopify OAuth (install + callback), token storage in `data/stores.json`.
- **Frontend** (`static/index.html`): Chat UI with a “Connect your store” link.
- **Connect page** (`/connect`): Form to enter store URL and start OAuth.
- **.env**: `DEEPSEEK_API_KEY`; optional `SHOPIFY_APP_URL`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET` for store connection (redirect_uri = `SHOPIFY_APP_URL` + `/auth/shopify/callback`).

## Next

- **Order lookup:** When a customer gives order number + email, call Shopify’s API (using the stored token) and inject order/refund data into the chat so the bot can answer with real data.
