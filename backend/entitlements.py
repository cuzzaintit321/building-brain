"""Resolve current paid access from Stripe rather than trusting browser state."""
from fastapi import HTTPException
from .billing import initialize, stripe, price_map, require_pilot
from .main import db

def active_plan():
    require_pilot()
    initialize()
    with db() as c:
        customer=c.execute("SELECT customer FROM billing_workspace WHERE id=1").fetchone()[0]
    if not customer:
        return None
    result=stripe("GET","subscriptions?customer="+customer+"&status=all&limit=100")
    if result.get("has_more"):
        raise HTTPException(503,"Subscription review required")
    plans=set()
    for subscription in result["data"]:
        if subscription["status"] not in ("active","trialing"):
            continue
        items=subscription["items"]["data"]
        if len(items)!=1:
            continue
        price=items[0]["price"]["id"]
        for key,value in price_map().items():
            if value and value==price:
                plans.add(key.split(":")[0])
    if len(plans)>1:
        raise HTTPException(503,"Subscription review required")
    return next(iter(plans),None)
