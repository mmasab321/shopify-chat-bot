"""
Fetch shop, products, and orders from Shopify REST Admin API using stored token.
"""
import httpx

API_VERSION = "2024-01"
BASE = "https://{shop}/admin/api/{version}"


def _headers(token: str) -> dict:
    return {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}


def get_shop_info(shop: str, token: str) -> dict | None:
    """GET shop.json. Returns shop dict or None on error."""
    url = f"{BASE.format(shop=shop, version=API_VERSION)}/shop.json"
    try:
        r = httpx.get(url, headers=_headers(token), timeout=15)
        r.raise_for_status()
        return r.json().get("shop")
    except Exception:
        return None


def get_products(shop: str, token: str, limit: int = 25) -> list[dict]:
    """GET products.json. Returns list of product dicts (id, title, body_html, variants with price)."""
    url = f"{BASE.format(shop=shop, version=API_VERSION)}/products.json"
    try:
        r = httpx.get(url, headers=_headers(token), params={"limit": limit}, timeout=15)
        r.raise_for_status()
        return r.json().get("products", [])
    except Exception:
        return []


def get_order_by_number_and_email(shop: str, token: str, order_number: str, email: str) -> dict | None:
    """Find an order by order number and customer email. Returns order dict or None."""
    # Shopify order_number is integer; name is like "#1001". Search by status=any and filter.
    url = f"{BASE.format(shop=shop, version=API_VERSION)}/orders.json"
    try:
        r = httpx.get(
            url,
            headers=_headers(token),
            params={"status": "any", "limit": 250},
            timeout=15,
        )
        r.raise_for_status()
        orders = r.json().get("orders", [])
        email_lower = email.strip().lower()
        order_num = str(order_number).strip().lstrip("#")
        for o in orders:
            if not order_num and str(o.get("email", "")).lower() == email_lower:
                return o
            if order_num and str(o.get("order_number", "")).strip() == order_num:
                if str(o.get("email", "")).lower() == email_lower:
                    return o
                return o  # match by number only if email not provided
        return None
    except Exception:
        return None


def build_store_context(shop: str, token: str, include_products: bool = True) -> str:
    """Build a context string (shop info + products) for the LLM."""
    parts = []
    shop_info = get_shop_info(shop, token)
    if shop_info:
        parts.append(
            f"Store: {shop_info.get('name', 'N/A')}. "
            f"Primary domain: {shop_info.get('primary_domain', {}).get('url', shop)}. "
            f"Currency: {shop_info.get('currency', 'USD')}."
        )
    if include_products:
        products = get_products(shop, token)
        if products:
            lines = []
            for p in products[:20]:
                title = p.get("title", "?")
                variants = p.get("variants", [])
                prices = [v.get("price") for v in variants if v.get("price")]
                price_str = f" ${prices[0]}" if prices else ""
                lines.append(f"- {title}{price_str}")
            parts.append("Products (name and price): " + "; ".join(lines))
    return " ".join(parts) if parts else ""


def build_order_context(shop: str, token: str, order_number: str, email: str) -> str:
    """Fetch one order by number + email and return a short context string for the LLM."""
    order = get_order_by_number_and_email(shop, token, order_number, email)
    if not order:
        return ""
    lines = [
        f"Order #{order.get('order_number')} ({order.get('name', '')})",
        f"Email: {order.get('email')}",
        f"Total: {order.get('total_price')} {order.get('currency', '')}",
        f"Fulfillment: {order.get('fulfillment_status') or 'unfulfilled'}",
    ]
    return ". ".join(lines)
