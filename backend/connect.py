"""Connected workforce API for the canonical Building Brain backend."""
import hashlib, hmac, secrets, time
from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel, Field
from typing import Literal

def install(app, db, auth):
    router=APIRouter(prefix="/api/connect")
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS connect_users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, digest TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS connect_access(user_id INTEGER REFERENCES connect_users(id), property_id INTEGER REFERENCES properties(id), PRIMARY KEY(user_id,property_id));
        CREATE TABLE IF NOT EXISTS connect_sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER REFERENCES connect_users(id),expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS connect_assignments(order_id INTEGER PRIMARY KEY REFERENCES orders(id),user_id INTEGER REFERENCES connect_users(id),revision INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS connect_events(id INTEGER PRIMARY KEY,order_id INTEGER REFERENCES orders(id),property_id INTEGER REFERENCES properties(id),actor TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL DEFAULT '',created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS connect_attempts(username TEXT PRIMARY KEY, count INTEGER NOT NULL, started INTEGER NOT NULL);
        """)
    def digest(password,salt):
        return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
    def tokenhash(token): return hashlib.sha256(token.encode()).hexdigest()
    def user(request:Request):
        header=request.headers.get("Authorization","")
        if not header.startswith("Bearer "): raise HTTPException(401,"Sign in required")
        with db() as c:
            r=c.execute("SELECT u.id,u.username FROM connect_sessions s JOIN connect_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.active=1",(tokenhash(header[7:]),int(time.time()))).fetchone()
            if not r: raise HTTPException(401,"Invalid session")
            return dict(r)
    class Account(BaseModel):
        username:str=Field(min_length=3,max_length=80,pattern=r"^[a-zA-Z0-9_.-]+$")
        password:str=Field(min_length=12,max_length=128)
        property_ids:list[int]=Field(min_length=1,max_length=1000)
    @router.post("/admin/users",dependencies=[Depends(auth)])
    def create_account(x:Account):
        salt=secrets.token_hex(16)
        with db() as c:
            if c.execute("SELECT 1 FROM connect_users WHERE username=?",(x.username.lower(),)).fetchone(): raise HTTPException(409,"Username exists")
            for pid in set(x.property_ids):
                if not c.execute("SELECT 1 FROM properties WHERE id=?",(pid,)).fetchone(): raise HTTPException(404,"Property not found")
            uid=c.execute("INSERT INTO connect_users(username,salt,digest) VALUES(?,?,?)",(x.username.lower(),salt,digest(x.password,salt))).lastrowid
            c.executemany("INSERT INTO connect_access VALUES(?,?)",[(uid,p) for p in set(x.property_ids)])
        return {"id":uid}
    @router.get("/admin/users",dependencies=[Depends(auth)])
    def accounts():
        with db() as c:return [dict(r) for r in c.execute("SELECT id,username,active FROM connect_users ORDER BY username")]
    @router.delete("/admin/users/{uid}",dependencies=[Depends(auth)])
    def disable(uid:int):
        with db() as c:
            c.execute("UPDATE connect_users SET active=0 WHERE id=?",(uid,))
            c.execute("DELETE FROM connect_sessions WHERE user_id=?",(uid,))
        return {"ok":True}
    class Login(BaseModel):
        username:str=Field(max_length=80)
        password:str=Field(max_length=128)
    @router.post("/login")
    def login(x:Login):
        name=x.username.lower(); now=int(time.time()); valid=False
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            a=c.execute("SELECT * FROM connect_attempts WHERE username=?",(name,)).fetchone()
            if a and now-a["started"]<900 and a["count"]>=5: raise HTTPException(429,"Try again later")
            r=c.execute("SELECT * FROM connect_users WHERE username=?",(name,)).fetchone()
            computed=digest(x.password,r["salt"] if r else "00"*16)
            valid=bool(r and r["active"] and hmac.compare_digest(computed,r["digest"]))
            if valid:
                token=secrets.token_urlsafe(32)
                c.execute("DELETE FROM connect_attempts WHERE username=?",(name,))
                c.execute("DELETE FROM connect_sessions WHERE expires<=?",(now,))
                c.execute("INSERT INTO connect_sessions VALUES(?,?,?)",(tokenhash(token),r["id"],now+28800))
            else:
                count=a["count"]+1 if a and now-a["started"]<900 else 1
                started=a["started"] if count>1 else now
                c.execute("INSERT OR REPLACE INTO connect_attempts VALUES(?,?,?)",(name,count,started))
        if not valid: raise HTTPException(401,"Invalid credentials")
        return {"token":token,"expires_in":28800}
    @router.post("/logout")
    def logout(request:Request,u=Depends(user)):
        with db() as c:c.execute("DELETE FROM connect_sessions WHERE token_hash=?",(tokenhash(request.headers["Authorization"][7:]),))
        return {"ok":True}
    class Assignment(BaseModel):
        user_id:int
    @router.put("/admin/orders/{oid}/assign",dependencies=[Depends(auth)])
    def assign(oid:int,x:Assignment):
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            r=c.execute("SELECT o.property_id,u.username FROM orders o JOIN connect_access a ON a.property_id=o.property_id JOIN connect_users u ON u.id=a.user_id WHERE o.id=? AND u.id=? AND u.active=1",(oid,x.user_id)).fetchone()
            if not r:raise HTTPException(404,"Order or authorized technician not found")
            c.execute("INSERT INTO connect_assignments(order_id,user_id) VALUES(?,?) ON CONFLICT(order_id) DO UPDATE SET user_id=excluded.user_id,revision=revision+1",(oid,x.user_id))
            c.execute("UPDATE orders SET assignee=? WHERE id=?",(r["username"],oid))
            c.execute("INSERT INTO connect_events(order_id,property_id,actor,action,detail) VALUES(?,?,?,?,?)",(oid,r["property_id"],"admin","assigned",r["username"]))
        return {"ok":True}
    @router.get("/orders")
    def orders(u=Depends(user)):
        with db() as c:return [dict(r) for r in c.execute("SELECT o.*,a.revision FROM orders o JOIN connect_assignments a ON a.order_id=o.id JOIN connect_access p ON p.property_id=o.property_id AND p.user_id=a.user_id WHERE a.user_id=? ORDER BY o.id DESC",(u["id"],))]
    class Progress(BaseModel):
        status:Literal["In Progress","Completed"]
        revision:int=Field(ge=0)
        resolution:str=Field(default="",max_length=10000)
    @router.patch("/orders/{oid}")
    def progress(oid:int,x:Progress,u=Depends(user)):
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            r=c.execute("SELECT o.property_id,o.status,a.revision FROM orders o JOIN connect_assignments a ON a.order_id=o.id JOIN connect_access p ON p.property_id=o.property_id AND p.user_id=a.user_id JOIN connect_users u ON u.id=a.user_id WHERE o.id=? AND a.user_id=? AND u.active=1",(oid,u["id"])).fetchone()
            if not r:raise HTTPException(404,"Order not found")
            if r["revision"]!=x.revision or r["status"]=="Completed":raise HTTPException(409,"Refresh order")
            if x.status=="Completed" and not x.resolution.strip():raise HTTPException(422,"Resolution required")
            c.execute("UPDATE orders SET status=?,resolution=?,completed_at=CASE WHEN ?='Completed' THEN CURRENT_TIMESTAMP ELSE '' END WHERE id=?",(x.status,x.resolution,x.status,oid))
            c.execute("UPDATE connect_assignments SET revision=revision+1 WHERE order_id=?",(oid,))
            c.execute("INSERT INTO connect_events(order_id,property_id,actor,action,detail) VALUES(?,?,?,?,?)",(oid,r["property_id"],u["username"],x.status,x.resolution))
        return {"revision":x.revision+1}
    @router.get("/admin/activity",dependencies=[Depends(auth)])
    def activity(after:int=0):
        with db() as c:return [dict(r) for r in c.execute("SELECT e.*,o.title FROM connect_events e JOIN orders o ON o.id=e.order_id WHERE e.id>? ORDER BY e.id LIMIT 200",(after,))]
    # Photo bytes stay in the authenticated database, never a public static directory.
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS connect_photos(
            id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders(id),
            property_id INTEGER NOT NULL REFERENCES properties(id),
            user_id INTEGER NOT NULL REFERENCES connect_users(id),
            category TEXT NOT NULL, caption TEXT NOT NULL, mime TEXT NOT NULL,
            data BLOB NOT NULL, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        c.execute("CREATE INDEX IF NOT EXISTS connect_photos_order ON connect_photos(order_id,id)")
    def photo_access(c,oid,uid):
        r=c.execute("""SELECT o.property_id FROM orders o
            JOIN connect_assignments a ON a.order_id=o.id
            JOIN connect_access p ON p.property_id=o.property_id AND p.user_id=a.user_id
            JOIN connect_users u ON u.id=a.user_id AND u.active=1
            WHERE o.id=? AND a.user_id=?""",(oid,uid)).fetchone()
        if not r:raise HTTPException(404,"Assigned order not found")
        return r["property_id"]
    @router.post("/orders/{oid}/photos",status_code=201)
    async def add_photo(oid:int,photo:UploadFile=File(...),category:Literal["Before","After","Progress","Issue"]=Form("Progress"),caption:str=Form("",max_length=1000),u=Depends(user)):
        with db() as c:photo_access(c,oid,u["id"])
        data=await photo.read(5*1024*1024+1)
        if len(data)>5*1024*1024:raise HTTPException(413,"Maximum photo size 5 MB")
        if data.startswith(bytes.fromhex("ffd8ff")):mime="image/jpeg"
        elif data.startswith(bytes.fromhex("89504e470d0a1a0a")):mime="image/png"
        elif data[:4]==b"RIFF" and data[8:12]==b"WEBP":mime="image/webp"
        else:raise HTTPException(415,"Use JPEG, PNG or WebP")
        # Decode and re-encode to validate pixels and discard metadata, including GPS EXIF.
        try:
            from PIL import Image
            import io
            with Image.open(io.BytesIO(data)) as im:
                if im.width*im.height>20000000:raise ValueError("Image too large")
                im.load()
                im.thumbnail((2400,2400))
                out=io.BytesIO()
                im.convert("RGB").save(out,format="JPEG",quality=85)
                data=out.getvalue();mime="image/jpeg"
        except Exception:raise HTTPException(422,"Invalid or oversized photo")
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            pid=photo_access(c,oid,u["id"])
            if c.execute("SELECT COUNT(*) FROM connect_photos WHERE order_id=?",(oid,)).fetchone()[0]>=50:raise HTTPException(409,"Maximum 50 photos per order")
            i=c.execute("INSERT INTO connect_photos(order_id,property_id,user_id,category,caption,mime,data) VALUES(?,?,?,?,?,?,?)",(oid,pid,u["id"],category,caption,mime,data)).lastrowid
            c.execute("INSERT INTO connect_events(order_id,property_id,actor,action,detail) VALUES(?,?,?,?,?)",(oid,pid,u["username"],"photo uploaded",category+" #"+str(i)))
        return {"id":i}
    def photo_list(c,oid):
        return [dict(r) for r in c.execute("""SELECT p.id,p.order_id,p.category,p.caption,p.created_at,u.username
            FROM connect_photos p JOIN connect_users u ON u.id=p.user_id
            JOIN orders o ON o.id=p.order_id AND o.property_id=p.property_id
            WHERE p.order_id=? ORDER BY p.id DESC""",(oid,))]
    @router.get("/orders/{oid}/photos")
    def worker_photos(oid:int,u=Depends(user)):
        with db() as c:
            photo_access(c,oid,u["id"])
            return photo_list(c,oid)
    @router.get("/admin/orders/{oid}/photos",dependencies=[Depends(auth)])
    def admin_photos(oid:int):
        with db() as c:return photo_list(c,oid)
    def photo_response(c,oid,pid):
        r=c.execute("""SELECT p.data,p.mime FROM connect_photos p JOIN orders o ON o.id=p.order_id AND o.property_id=p.property_id WHERE p.id=? AND p.order_id=?""",(pid,oid)).fetchone()
        if not r:raise HTTPException(404,"Photo not found")
        return Response(content=r["data"],media_type=r["mime"],headers={"Cache-Control":"private, no-store","X-Content-Type-Options":"nosniff"})
    @router.get("/orders/{oid}/photos/{pid}")
    def worker_photo(oid:int,pid:int,u=Depends(user)):
        with db() as c:
            photo_access(c,oid,u["id"])
            return photo_response(c,oid,pid)
    @router.get("/admin/orders/{oid}/photos/{pid}",dependencies=[Depends(auth)])
    def admin_photo(oid:int,pid:int):
        with db() as c:return photo_response(c,oid,pid)
    app.include_router(router)
