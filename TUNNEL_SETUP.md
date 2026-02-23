# Fix "matching hosts" – use a tunnel (skip localhost)

Shopify’s dev dashboard often rejects localhost/127.0.0.1. Use a **public HTTPS URL** so OAuth works.

## 1. Install a tunnel (pick one)

**Option A – ngrok** (run in **macOS Terminal**, not Cursor):

```bash
brew install ngrok   # if needed
ngrok http 8000
```

**Option B – Cloudflare Tunnel** (no account required for quick try):

```bash
brew install cloudflared
cloudflared tunnel --url http://localhost:8000
```

Copy the **HTTPS** URL (e.g. `https://wires-councils-identical-attachment.trycloudfla.com` or `https://xxx.trycloudflare.com`).  
**Important:** Your app must be running first (`uvicorn ... --host 0.0.0.0 --port 8000`), or you’ll get a 502 when visiting the tunnel URL.

## 2. App and Shopify on the same base URL

Your app must be reachable at that URL. With ngrok/cloudflared, that’s already the case (they forward to your localhost:8000).

1. **Start your app** (in Cursor or any terminal):
   ```bash
   cd /Users/muhammadmusab/shopify-chat-bot && source .venv/bin/activate && uvicorn backend.main:app --host 0.0.0.0 --port 8000
   ```

2. **Start the tunnel** in **another terminal** (e.g. macOS Terminal):
   ```bash
   ngrok http 8000
   ```
   Copy the HTTPS URL (e.g. `https://a1b2c3.ngrok-free.app`).

3. **In Shopify** (your app → Versions):
   - **App URL:** `https://a1b2c3.ngrok-free.app` (your tunnel URL, no path)
   - **Redirect URLs:** `https://a1b2c3.ngrok-free.app/auth/shopify/callback`
   Save and release the version.

4. **In `.env`** set:
   ```env
   SHOPIFY_APP_URL=https://a1b2c3.ngrok-free.app
   ```
   (Use your real tunnel URL. Keep `SHOPIFY_CLIENT_ID` and `SHOPIFY_CLIENT_SECRET` as they are.)

5. **Restart uvicorn** (Ctrl+C then run the uvicorn command again).

6. **Open the tunnel URL** in the browser (e.g. `https://a1b2c3.ngrok-free.app/connect`), enter your store, click **Connect with Shopify**. Complete the flow on that URL.

After the store is connected, you can keep developing on localhost for chat; the stored token will still work. You only need the tunnel again if you connect another store or re-auth.
