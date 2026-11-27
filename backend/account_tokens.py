"""Account token storage; delivery and public routes must be wired before launch."""
import hashlib
import secrets
import time

def issue(registry, user_id, purpose, ttl=1800):
    if purpose not in ("verify_email","reset_password"):
        raise ValueError("Invalid token purpose")
    token=secrets.token_urlsafe(32)
    with registry.connect() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS account_tokens (
            digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            purpose TEXT NOT NULL, expires INTEGER NOT NULL)""")
        c.execute("DELETE FROM account_tokens WHERE user_id=? AND purpose=?",(user_id,purpose))
        c.execute("INSERT INTO account_tokens VALUES (?,?,?,?)",(hashlib.sha256(token.encode()).hexdigest(),user_id,purpose,int(time.time())+ttl))
    return token

def consume(registry, token, purpose, apply):
    if purpose not in ("verify_email","reset_password") or len(token)>128:
        return False
    with registry.connect() as c:
        c.execute("BEGIN IMMEDIATE")
        c.execute("""CREATE TABLE IF NOT EXISTS account_tokens (
            digest TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
            purpose TEXT NOT NULL, expires INTEGER NOT NULL)""")
        digest=hashlib.sha256(token.encode()).hexdigest()
        row=c.execute("SELECT user_id FROM account_tokens WHERE digest=? AND purpose=? AND expires>?",(digest,purpose,int(time.time()))).fetchone()
        if not row:
            return False
        apply(c,row[0])
        c.execute("DELETE FROM account_tokens WHERE digest=?",(digest,))
        return True
