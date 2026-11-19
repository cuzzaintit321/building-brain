"""Single-company communications prototype. Authenticated HTTP signaling;
media travels via WebRTC, never through this API. No recording."""
import os, time, secrets, json, hashlib, hmac, base64
from typing import Literal
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field

def install(router,db,user):
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS connect_messages(id INTEGER PRIMARY KEY,sender INTEGER NOT NULL REFERENCES connect_users(id),recipient INTEGER NOT NULL REFERENCES connect_users(id),body TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE INDEX IF NOT EXISTS connect_message_pair ON connect_messages(sender,recipient,id);
        CREATE TABLE IF NOT EXISTS connect_calls(id TEXT PRIMARY KEY,caller INTEGER NOT NULL REFERENCES connect_users(id),callee INTEGER NOT NULL REFERENCES connect_users(id),kind TEXT NOT NULL,status TEXT NOT NULL,created INTEGER NOT NULL,updated INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS connect_signals(id INTEGER PRIMARY KEY,call_id TEXT NOT NULL REFERENCES connect_calls(id),sender INTEGER NOT NULL REFERENCES connect_users(id),kind TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS connect_signal_call ON connect_signals(call_id,id);
        """)
    def active(c,uid):
        return c.execute("SELECT id,username FROM connect_users WHERE id=? AND active=1",(uid,)).fetchone()
    def peer(c,uid,other):
        if uid==other or not active(c,uid) or not active(c,other):raise HTTPException(404,"Contact unavailable")
        if not c.execute("SELECT 1 FROM connect_access a JOIN connect_access b ON a.property_id=b.property_id WHERE a.user_id=? AND b.user_id=?",(uid,other)).fetchone():raise HTTPException(404,"Contact unavailable")
    def expire(c):
        now=int(time.time())
        c.execute("UPDATE connect_calls SET status='ended',updated=? WHERE (status='ringing' AND created<?) OR (status='accepted' AND updated<?)",(now,now-60,now-14400))
        c.execute("DELETE FROM connect_signals WHERE call_id IN (SELECT id FROM connect_calls WHERE status IN ('ended','declined') AND updated<?)",(now-300,))
    def call_for(c,cid,uid):
        r=c.execute("SELECT * FROM connect_calls WHERE id=? AND (caller=? OR callee=?)",(cid,uid,uid)).fetchone()
        if not r:raise HTTPException(404,"Call not found")
        peer(c,uid,r["callee"] if r["caller"]==uid else r["caller"])
        return r
    @router.get("/contacts")
    def contacts(u=Depends(user)):
        with db() as c:
            people=[dict(r) for r in c.execute("SELECT DISTINCT b.id,b.username FROM connect_users b JOIN connect_access ba ON ba.user_id=b.id JOIN connect_access a ON a.property_id=ba.property_id WHERE a.user_id=? AND b.id!=? AND b.active=1 ORDER BY b.username",(u["id"],u["id"]))]
        return {"me":u,"contacts":people}
    class Message(BaseModel):
        recipient:int
        body:str=Field(min_length=1,max_length=4000)
    @router.post("/messages",status_code=201)
    def send(x:Message,u=Depends(user)):
        if not x.body.strip():raise HTTPException(422,"Write a message")
        with db() as c:
            c.execute("BEGIN IMMEDIATE");peer(c,u["id"],x.recipient)
            if c.execute("SELECT COUNT(*) FROM connect_messages WHERE sender=? AND created_at>=datetime('now','-1 minute')",(u["id"],)).fetchone()[0]>=60:raise HTTPException(429,"Slow down")
            i=c.execute("INSERT INTO connect_messages(sender,recipient,body) VALUES(?,?,?)",(u["id"],x.recipient,x.body.strip())).lastrowid
        return {"id":i}
    @router.get("/messages/{other}")
    def messages(other:int,u=Depends(user)):
        with db() as c:
            peer(c,u["id"],other)
            return [dict(r) for r in c.execute("SELECT * FROM (SELECT id,sender,recipient,body,created_at FROM connect_messages WHERE (sender=? AND recipient=?) OR (sender=? AND recipient=?) ORDER BY id DESC LIMIT 100) ORDER BY id",(u["id"],other,other,u["id"]))]
    class Dial(BaseModel):
        recipient:int
        kind:Literal["voice","video"]
    @router.post("/calls",status_code=201)
    def dial(x:Dial,u=Depends(user)):
        now=int(time.time());cid=secrets.token_urlsafe(24)
        with db() as c:
            c.execute("BEGIN IMMEDIATE");expire(c);peer(c,u["id"],x.recipient)
            if c.execute("SELECT 1 FROM connect_calls WHERE status IN ('ringing','accepted') AND (caller IN (?,?) OR callee IN (?,?))",(u["id"],x.recipient,u["id"],x.recipient)).fetchone():raise HTTPException(409,"Someone is already in a call")
            if c.execute("SELECT COUNT(*) FROM connect_calls WHERE caller=? AND created>=?",(u["id"],now-60)).fetchone()[0]>=5:raise HTTPException(429,"Too many calls")
            c.execute("INSERT INTO connect_calls VALUES(?,?,?,?,?,?,?)",(cid,u["id"],x.recipient,x.kind,"ringing",now,now))
        return {"id":cid}
    @router.get("/calls")
    def calls(u=Depends(user)):
        with db() as c:
            expire(c)
            result=[]
            for r in c.execute("SELECT * FROM connect_calls WHERE (caller=? OR callee=?) AND status IN ('ringing','accepted')",(u["id"],u["id"])):
                try:peer(c,u["id"],r["callee"] if r["caller"]==u["id"] else r["caller"])
                except HTTPException:continue
                result.append(dict(r))
            return result
    class Decision(BaseModel):
        action:Literal["accept","decline","end"]
    @router.post("/calls/{cid}/decision")
    def decide(cid:str,x:Decision,u=Depends(user)):
        with db() as c:
            c.execute("BEGIN IMMEDIATE");expire(c);r=call_for(c,cid,u["id"])
            if x.action in ("accept","decline") and (r["callee"]!=u["id"] or r["status"]!="ringing"):raise HTTPException(409,"Call no longer ringing")
            status={"accept":"accepted","decline":"declined","end":"ended"}[x.action]
            if x.action=="end" and r["status"] not in ("ringing","accepted"):return {"status":r["status"]}
            c.execute("UPDATE connect_calls SET status=?,updated=? WHERE id=?",(status,int(time.time()),cid))
        return {"status":status}
    class Signal(BaseModel):
        kind:Literal["offer","answer","ice"]
        payload:dict
    @router.post("/calls/{cid}/signals")
    def signal(cid:str,x:Signal,u=Depends(user)):
        data=json.dumps(x.payload)
        if len(data)>65536:raise HTTPException(413,"Signal too large")
        with db() as c:
            c.execute("BEGIN IMMEDIATE");expire(c);r=call_for(c,cid,u["id"])
            if r["status"]!="accepted":raise HTTPException(409,"Call not accepted")
            if (x.kind=="offer" and r["caller"]!=u["id"]) or (x.kind=="answer" and r["callee"]!=u["id"]):raise HTTPException(403,"Invalid signaling role")
            if c.execute("SELECT COUNT(*) FROM connect_signals WHERE call_id=? AND sender=?",(cid,u["id"])).fetchone()[0]>=250:raise HTTPException(429,"Signal limit")
            i=c.execute("INSERT INTO connect_signals(call_id,sender,kind,payload) VALUES(?,?,?,?)",(cid,u["id"],x.kind,data)).lastrowid
        return {"id":i}
    @router.get("/calls/{cid}/signals")
    def signals(cid:str,after:int=0,u=Depends(user)):
        with db() as c:
            expire(c);r=call_for(c,cid,u["id"])
            items=[{"id":s["id"],"kind":s["kind"],"payload":json.loads(s["payload"])} for s in c.execute("SELECT id,kind,payload FROM connect_signals WHERE call_id=? AND sender!=? AND id>? ORDER BY id LIMIT 100",(cid,u["id"],after))]
        return {"status":r["status"],"signals":items}
    @router.get("/ice-config")
    def ice(u=Depends(user)):
        urls=[s.strip() for s in os.environ.get("CONNECT_STUN_URLS","").split(",") if s.strip()]
        servers=[{"urls":urls}] if urls else []
        turn=[s.strip() for s in os.environ.get("CONNECT_TURN_URLS","").split(",") if s.strip()]
        secret=os.environ.get("CONNECT_TURN_SECRET","")
        if turn and secret:
            username=str(int(time.time())+14400)+":"+str(u["id"])
            credential=base64.b64encode(hmac.new(secret.encode(),username.encode(),hashlib.sha1).digest()).decode()
            servers.append({"urls":turn,"username":username,"credential":credential})
        return {"iceServers":servers}
