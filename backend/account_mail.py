import hashlib
import os
import secrets
import smtplib
import ssl
from email.message import EmailMessage

def send_token(registry,email,purpose):
    email=email.strip().casefold()
    token=secrets.token_urlsafe(32)
    digest=hashlib.sha256(token.encode()).hexdigest()
    with registry.connect() as c:
        c.execute("CREATE TABLE IF NOT EXISTS account_tokens (digest TEXT PRIMARY KEY, email TEXT NOT NULL, purpose TEXT NOT NULL, expires INTEGER NOT NULL)")
        c.execute("DELETE FROM account_tokens WHERE email=? AND purpose=?",(email,purpose))
        c.execute("INSERT INTO account_tokens VALUES (?,?,?,strftime('%s','now')+1800)",(digest,email,purpose))
    msg=EmailMessage()
    msg["From"]=os.environ["ACCOUNT_MAIL_FROM"]
    msg["To"]=email
    msg["Subject"]="Building Brain account "+purpose
    msg.set_content("Your single-use "+purpose+" code (expires in 30 minutes): "+token)
    with smtplib.SMTP_SSL(os.environ["ACCOUNT_SMTP_HOST"],int(os.getenv("ACCOUNT_SMTP_PORT","465")),timeout=15,context=ssl.create_default_context()) as smtp:
        smtp.login(os.environ["ACCOUNT_SMTP_USER"],os.environ["ACCOUNT_SMTP_PASSWORD"])
        smtp.send_message(msg)

def consume(c,email,purpose,token):
    digest=hashlib.sha256(token.encode()).hexdigest()
    result=c.execute("DELETE FROM account_tokens WHERE digest=? AND email=? AND purpose=? AND expires>strftime('%s','now')",(digest,email.strip().casefold(),purpose))
    if result.rowcount!=1:
        raise ValueError("Invalid or expired code")
