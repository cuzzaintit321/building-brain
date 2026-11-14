"""Scoped mobile API. Existing administrator routes remain separate."""
import hashlib, secrets, time, re
from fastapi import APIRouter, HTTPException, Request, Depends
from pydantic import BaseModel, Field
from .db import db, one
from .facilityguard import list_scoped

router=APIRouter(prefix='/api/mobile')
def initialize_mobile():
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS mobile_users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, salt TEXT NOT NULL, password_hash TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 1);
        CREATE TABLE IF NOT EXISTS mobile_access(user_id INTEGER REFERENCES mobile_users(id) ON DELETE CASCADE, property_id INTEGER REFERENCES properties(id) ON DELETE CASCADE, role TEXT NOT NULL CHECK(role IN ('viewer','technician')), PRIMARY KEY(user_id,property_id));
        CREATE TABLE IF NOT EXISTS mobile_sessions(token_hash TEXT PRIMARY KEY,user_id INTEGER REFERENCES mobile_users(id) ON DELETE CASCADE,expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS mobile_attempts(username TEXT PRIMARY KEY, count INTEGER NOT NULL, until INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS mobile_audit(id INTEGER PRIMARY KEY,user_id INTEGER,property_id INTEGER,action TEXT,record_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        """)
def digest(s): return hashlib.sha256(s.encode()).hexdigest()
def password_hash(password,salt):
    return hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
class Login(BaseModel):
    username:str=Field(min_length=1,max_length=80)
    password:str=Field(min_length=12,max_length=256)
class Account(Login):
    property_id:int=Field(gt=0)
    role:str
class Status(BaseModel):
    status:str
    expected_status:str
@router.post('/admin/accounts')
def account(item:Account):
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{1,80}',item.username) or item.role not in ('viewer','technician'):
        raise HTTPException(422,'Invalid account or role')
    with db() as c:
        if not one(c,'SELECT id FROM properties WHERE id=?',(item.property_id,)): raise HTTPException(404,'Property not found')
        if one(c,'SELECT id FROM mobile_users WHERE username=?',(item.username,)): raise HTTPException(409,'Account already exists')
        salt=secrets.token_hex(16)
        uid=c.execute('INSERT INTO mobile_users(username,salt,password_hash) VALUES(?,?,?)',(item.username,salt,password_hash(item.password,salt))).lastrowid
        c.execute('INSERT INTO mobile_access VALUES(?,?,?)',(uid,item.property_id,item.role))
    return {'id':uid}
@router.post('/admin/accounts/{uid}/disable')
def disable(uid:int):
    with db() as c:
        c.execute('UPDATE mobile_users SET enabled=0 WHERE id=?',(uid,))
        c.execute('DELETE FROM mobile_sessions WHERE user_id=?',(uid,))
    return {'disabled':uid}
@router.post('/login')
def login(item:Login):
    now=int(time.time())
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute('DELETE FROM mobile_attempts WHERE until<=?',(now,))
        c.execute('DELETE FROM mobile_sessions WHERE expires<=?',(now,))
        a=one(c,'SELECT * FROM mobile_attempts WHERE username=?',(item.username,))
        if a and a['count']>=5: raise HTTPException(429,'Try again later')
        u=one(c,'SELECT * FROM mobile_users WHERE username=?',(item.username,))
        calculated=password_hash(item.password,u['salt'] if u else '00'*16)
        if not u or not u['enabled'] or not secrets.compare_digest(calculated,u['password_hash']):
            c.execute('INSERT INTO mobile_attempts VALUES(?,1,?) ON CONFLICT(username) DO UPDATE SET count=count+1',(item.username,now+900))
            c.commit()
            raise HTTPException(401,'Invalid credentials')
        c.execute('DELETE FROM mobile_attempts WHERE username=?',(item.username,))
        token=secrets.token_urlsafe(32)
        c.execute('INSERT INTO mobile_sessions VALUES(?,?,?)',(digest(token),u['id'],now+28800))
    return {'token':token,'expires_in':28800}
def identity(request:Request):
    raw=request.headers.get('authorization','')
    if not raw.startswith('Bearer ') or len(raw)>200: raise HTTPException(401,'Sign in required')
    with db() as c:
        u=one(c,'SELECT u.id FROM mobile_sessions s JOIN mobile_users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.enabled=1',(digest(raw[7:]),int(time.time())))
        if not u: raise HTTPException(401,'Session expired')
        return u['id']
def access(c,uid,pid,write=False):
    a=one(c,'SELECT role FROM mobile_access WHERE user_id=? AND property_id=?',(uid,pid))
    if not a or (write and a['role']!='technician'): raise HTTPException(403,'Access denied')
@router.post('/logout')
def logout(request:Request,uid:int=Depends(identity)):
    with db() as c: c.execute('DELETE FROM mobile_sessions WHERE token_hash=?',(digest(request.headers['authorization'][7:]),))
    return {'ok':True}
@router.get('/properties')
def properties(uid:int=Depends(identity)):
    with db() as c: return [dict(r) for r in c.execute('SELECT p.id,p.name,a.role FROM properties p JOIN mobile_access a ON p.id=a.property_id WHERE a.user_id=?',(uid,))]
@router.get('/properties/{pid}/{kind}')
def records(pid:int,kind:str,uid:int=Depends(identity)):
    with db() as c:
        access(c,uid,pid)
        if kind=='documents': return [dict(r) for r in c.execute('SELECT id,filename,pages FROM documents WHERE property_id=?',(pid,))]
        if kind=='assets': return [dict(r) for r in c.execute('SELECT * FROM assets WHERE property_id=? ORDER BY name',(pid,))]
        tables={'work-orders':'fg_work_orders','pm-plans':'fg_pm_plans','inspections':'fg_inspections'}
        if kind not in tables: raise HTTPException(404,'Unknown resource')
        return list_scoped(c,tables[kind],pid,None,'t.id DESC')
@router.patch('/properties/{pid}/work-orders/{rid}')
def update(pid:int,rid:int,item:Status,uid:int=Depends(identity)):
    if item.status not in ('in_progress','completed') or item.expected_status not in ('open','in_progress','blocked'): raise HTTPException(422,'Invalid transition')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        access(c,uid,pid,True)
        result=c.execute("UPDATE fg_work_orders SET status=?,completed_at=CASE WHEN ?='completed' THEN datetime('now') ELSE NULL END WHERE id=? AND property_id=? AND status=?",(item.status,item.status,rid,pid,item.expected_status))
        if result.rowcount!=1: raise HTTPException(409,'Record changed or unavailable; refresh')
        c.execute('INSERT INTO mobile_audit(user_id,property_id,action,record_id) VALUES(?,?,?,?)',(uid,pid,item.status,rid))
    return {'ok':True}

@router.get('/properties/{pid}/assets/{rid}/label')
def label(pid:int,rid:int,uid:int=Depends(identity)):
    with db() as c:
        access(c,uid,pid)
        if not one(c,'SELECT id FROM assets WHERE property_id=? AND id=?',(pid,rid)): raise HTTPException(404,'Asset not found')
    return {'payload':f'buildingbrain:asset:{rid}'}
