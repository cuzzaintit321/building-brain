"""Single-workspace Stripe billing pilot. Not public SaaS onboarding."""
import os, secrets, time, hmac, hashlib, json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from .main import auth, db

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

def origin():
    value = config("BILLING_PUBLIC_URL").rstrip("/")
    if not value.startswith("https://"):
        raise HTTPException(503, "HTTPS billing URL required")
    return value

def price_map():
    return {f"{p}:{i}": os.getenv(f"STRIPE_PRICE_{p.upper()}_{i.upper()}", "") for p in PLANS for i in ("monthly", "annual")}

class Checkout(BaseModel):
    plan: str
    interval: str = "monthly"

@router.get("/status", dependencies=[Depends(auth)])
def status():
    initialize()
    with db() as c:
        customer = c.execute("SELECT customer FROM billing_workspace WHERE id=1").fetchone()[0]
    subscriptions = []
    if enabled() and customer:
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
def checkout(x: Checkout):
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
            customer = stripe("POST", "customers", {"description":"Building Brain pilot workspace","metadata[application]":"building-brain"}, "building-brain-" + hashlib.sha256(os.environ["SECRET_KEY"].encode()).hexdigest())["id"]
            c.execute("UPDATE billing_workspace SET customer=? WHERE id=1",(customer,))
        existing = stripe("GET", "subscriptions?customer=" + customer + "&status=all&limit=100")
        if existing.get("has_more") or any(s["status"] not in ("canceled","incomplete_expired") for s in existing["data"]):
            raise HTTPException(409, "Manage existing subscription in billing portal")
        if previous:
            old = stripe("GET", "checkout/sessions/" + previous)
            if old["status"] == "open":
                stripe("POST", "checkout/sessions/" + previous + "/expire")
            elif old["status"] == "complete":
                raise HTTPException(409, "Previous checkout completed; review billing status")
        session = stripe("POST", "checkout/sessions", {"mode":"subscription","customer":customer,"line_items[0][price]":price,"line_items[0][quantity]":"1","success_url":base+"/billing","cancel_url":base+"/billing","subscription_data[metadata][application]":"building-brain"}, secrets.token_hex(24))
        c.execute("UPDATE billing_workspace SET checkout=? WHERE id=1",(session["id"],))
        return {"url":session["url"]}

@router.post("/portal", dependencies=[Depends(auth)])
def portal():
    require_pilot()
    initialize()
    with db() as c:
        customer = c.execute("SELECT customer FROM billing_workspace WHERE id=1").fetchone()[0]
    if not customer:
        raise HTTPException(409, "No billing customer")
    session = stripe("POST", "billing_portal/sessions", {"customer":customer,"configuration":config("STRIPE_PORTAL_CONFIGURATION"),"return_url":origin()+"/billing"})
    return {"url":session["url"]}
