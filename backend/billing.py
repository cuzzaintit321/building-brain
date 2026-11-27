"""Single-workspace Stripe billing pilot. Not public SaaS onboarding."""
import os, secrets, time, hmac, hashlib, json, sqlite3
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from .main import auth, db, WORKSPACE, REGISTRY, DATA

router = APIRouter(prefix="/api/billing")
PLANS = {"starter": (99, 990), "professional": (299, 2990), "enterprise": (799, 7990)}

def enabled():
    return os.getenv("BILLING_PILOT_ENABLED", "false").lower() == "true"

def config(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise HTTPException(503, "Billing configuration incomplete")
    return value

def stripe(method, path, data=None, key=None):
    headers = {"Authorization": "Bearer " + config("STRIPE_SECRET_KEY")}
    if key:
        headers["Idempotency-Key"] = key
    try:
        response = httpx.request(method, "https://api.stripe.com/v1/" + path, data=data, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, "Stripe request failed")

def initialize():
    with db() as c:
        c.execute("CREATE TABLE IF NOT EXISTS billing_workspace (id INTEGER PRIMARY KEY CHECK(id=1), customer TEXT, checkout TEXT)")
        c.execute("INSERT OR IGNORE INTO billing_workspace(id) VALUES(1)")

def require_pilot():
    if not enabled():
        raise HTTPException(503, "Billing pilot is disabled")
    if not config("STRIPE_SECRET_KEY").startswith(("sk_test_", "rk_test_")):
        raise HTTPException(503, "Only Stripe test mode is supported by this pilot")

def origin():
    value = config("BILLING_PUBLIC_URL").rstrip("/")
    if not value.startswith("https://"):
        raise HTTPException(503, "HTTPS billing URL required")
    return value

def price_map():
    return {f"{p}:{i}": os.getenv(f"STRIPE_PRICE_{p.upper()}_{i.upper()}", "") for p in PLANS for i in ("monthly", "annual")}

def billing_owner(request):
    uid, oid = request.session.get("user_id"), request.session.get("organization_id")
    if uid or oid:
        if not uid or not oid or REGISTRY.role(uid, oid) != "owner" or WORKSPACE.get() is None:
            raise HTTPException(403, "Company owner required")

class Checkout(BaseModel):
    plan: str
    interval: str = "monthly"

@router.get("/status", dependencies=[Depends(auth)])
def status(request: Request):
    billing_owner(request)
    initialize()
    with db() as c:
        customer = c.execute("SELECT customer FROM billing_workspace WHERE id=1").fetchone()[0]
    subscriptions = []
    if enabled() and customer:
        require_pilot()
        result = stripe("GET", "subscriptions?customer=" + customer + "&status=all&limit=100")
        prices = price_map()
        for s in result["data"]:
            items = s["items"]["data"]
            if len(items) != 1:
                continue
            match = next((k for k,v in prices.items() if v and v == items[0]["price"]["id"]), None)
            if match:
                subscriptions.append({"plan": match, "status": s["status"], "cancel_at_period_end": s.get("cancel_at_period_end", False)})
    return {"enabled": enabled(), "plans": PLANS, "subscriptions": subscriptions, "has_customer": bool(customer)}

@router.post("/checkout", dependencies=[Depends(auth)])
def checkout(x: Checkout, request: Request):
    billing_owner(request)
    require_pilot()
    base = origin()
    price = price_map().get(x.plan + ":" + x.interval)
    if not price:
        raise HTTPException(422, "Plan or price not configured")
    initialize()
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        customer, previous = c.execute("SELECT customer,checkout FROM billing_workspace WHERE id=1").fetchone()
        if not customer:
            customer = stripe("POST", "customers", {"description":"Building Brain pilot workspace","metadata[application]":"building-brain"}, "building-brain-" + hashlib.sha256((os.environ["SECRET_KEY"] + ":" + str(WORKSPACE.get() or "legacy")).encode()).hexdigest())["id"]
            c.execute("UPDATE billing_workspace SET customer=? WHERE id=1",(customer,))
        existing = stripe("GET", "subscriptions?customer=" + customer + "&status=all&limit=100")
        if existing.get("has_more") or any(s["status"] not in ("canceled","incomplete_expired") for s in existing["data"]):
            raise HTTPException(409, "Manage existing subscription in billing portal")
        if previous:
            old = stripe("GET", "checkout/sessions/" + previous)
            if old["status"] == "open":
                stripe("POST", "checkout/sessions/" + previous + "/expire")
            elif old["status"] == "complete" and not existing["data"]:
                raise HTTPException(409, "Previous checkout completed; review billing status")
        params = {"mode":"subscription","customer":customer,"line_items[0][price]":price,"line_items[0][quantity]":"1","success_url":base+"/billing","cancel_url":base+"/billing","subscription_data[metadata][application]":"building-brain","subscription_data[trial_period_days]":"14"}
        if existing["data"]:
            params.pop("subscription_data[trial_period_days]", None)
        session = stripe("POST", "checkout/sessions", params, secrets.token_hex(24))
        c.execute("UPDATE billing_workspace SET checkout=? WHERE id=1",(session["id"],))
        return {"url":session["url"]}

@router.post("/portal", dependencies=[Depends(auth)])
def portal(request: Request):
    billing_owner(request)
    require_pilot()
    initialize()
    with db() as c:
        customer = c.execute("SELECT customer FROM billing_workspace WHERE id=1").fetchone()[0]
    if not customer:
        raise HTTPException(409, "No billing customer")
    session = stripe("POST", "billing_portal/sessions", {"customer":customer,"configuration":config("STRIPE_PORTAL_CONFIGURATION"),"return_url":origin()+"/billing"})
    return {"url":session["url"]}


def verify_signature(payload, header, secret, now=None):
    parts = [p.split("=", 1) for p in header.split(",") if "=" in p]
    timestamps = [v for k,v in parts if k == "t"]
    signatures = [v for k,v in parts if k == "v1"]
    try:
        if len(timestamps) != 1 or abs((time.time() if now is None else now) - int(timestamps[0])) > 300:
            return False
        digest = hmac.new(secret.encode(), timestamps[0].encode() + b"." + payload, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(digest, v) for v in signatures)
    except (ValueError, TypeError):
        return False

@router.post("/webhook")
async def webhook(request: Request):
    require_pilot()
    payload = await request.body()
    if len(payload) > 1024 * 1024:
        raise HTTPException(413, "Event too large")
    if not verify_signature(payload, request.headers.get("stripe-signature", ""), config("STRIPE_WEBHOOK_SECRET")):
        raise HTTPException(400, "Invalid Stripe signature")
    try:
        event = json.loads(payload)
        event_id, kind = event["id"], event["type"]
        obj = event["data"]["object"]
        if not isinstance(event_id, str) or not isinstance(kind, str) or not isinstance(obj, dict):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        raise HTTPException(400, "Invalid event")
    if event.get("livemode") is not False or kind not in {
        "checkout.session.completed", "customer.subscription.created",
        "customer.subscription.updated", "customer.subscription.deleted",
        "invoice.paid", "invoice.payment_failed"
    }:
        return {"received": True, "ignored": True}
    # Stripe delivers account-wide events. Route only to a known customer.
    customer = obj.get("customer")
    if not isinstance(customer, str):
        return {"received": True, "ignored": True}
    with REGISTRY.connect() as c:
        ids = [row[0] for row in c.execute("SELECT id FROM organizations")]
    candidates = [None] + [DATA/"identity"/"workspaces"/oid for oid in ids]
    for workspace in candidates:
        path = (workspace or DATA)/"buildingbrain.db"
        if not path.is_file():
            continue
        token = WORKSPACE.set(workspace)
        try:
            with db() as c:
                if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='billing_workspace'").fetchone():
                    continue
                known = c.execute("SELECT customer FROM billing_workspace WHERE id=1").fetchone()
                if not known or known[0] != customer:
                    continue
                c.execute("CREATE TABLE IF NOT EXISTS billing_events (event_id TEXT PRIMARY KEY, kind TEXT NOT NULL, received_at TEXT DEFAULT CURRENT_TIMESTAMP)")
                result = c.execute("INSERT OR IGNORE INTO billing_events(event_id,kind) VALUES(?,?)", (event_id,kind))
                return {"received": True, "duplicate": result.rowcount == 0}
        finally:
            WORKSPACE.reset(token)
    return {"received": True, "ignored": True}


def active_plan():
    # Fail closed on missing configuration, unknown prices or Stripe failures.
    try:
        require_pilot()
        initialize()
        with db() as c:
            customer=c.execute("SELECT customer FROM billing_workspace WHERE id=1").fetchone()[0]
        if not customer:
            return False
        result=stripe("GET","subscriptions?customer="+customer+"&status=all&limit=100")
        allowed={v for v in price_map().values() if v}
        matches={key.split(':')[0] for key,value in price_map().items() if value and any(s['status'] in ('active','trialing') and len(s['items']['data'])==1 and s['items']['data'][0]['price']['id']==value for s in result['data'])}
        return next(iter(matches)) if len(matches)==1 and not result.get('has_more') else None
    except (HTTPException,KeyError,TypeError):
        return False

def current_plan():
    return bool(active_plan())


def entitlement():
    return bool(current_plan())

# Proposed pilot quotas; review before commercial activation.
LIMITS={"starter":{"properties":5,"assets":250},"professional":{"properties":25,"assets":2500},"enterprise":{"properties":100,"assets":10000}}

def enforce_quota(c, resource, plan):
    if resource not in ("properties","assets") or plan not in LIMITS:
        raise HTTPException(402,"Active subscription required")
    count=c.execute("SELECT COUNT(*) FROM "+resource).fetchone()[0]
    if count>=LIMITS[plan][resource]:
        raise HTTPException(409,"Plan resource limit reached")
