"""Building Brain FastAPI application: authenticated single-organization MVP."""
from __future__ import annotations
import base64
import hashlib
import os
import re
import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware
from .ai import ask_llm
from .db import connect, db, ensure_building, ensure_property, initialize, one, remove_chunks, rowdict, database_path
from .ingest import IngestError, MAX_BYTES, SUPPORTED, chunks, extract
from .search import search

BASE=Path(__file__).resolve().parent

@asynccontextmanager
async def lifespan(app):
    password=os.getenv('APP_PASSWORD','')
    if len(password)<12 or password=='replace-with-long-random-password':
        raise RuntimeError('Set a unique APP_PASSWORD of at least 12 characters (see .env.example).')
    initialize()
    yield

app=FastAPI(title='Building Brain',version='0.1.0',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)

class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self,request,call_next):
        if request.url.path == '/healthz':
            return await call_next(request)
        raw=request.headers.get('authorization','')
        allowed=False
        if raw.startswith('Basic '):
            try:
                decoded=base64.b64decode(raw[6:],validate=True).decode('utf-8')
                username,password=decoded.split(':',1)
                allowed=secrets.compare_digest(username,os.getenv('APP_USER','admin')) and secrets.compare_digest(password,os.getenv('APP_PASSWORD',''))
            except (ValueError,UnicodeError):
                pass
        if not allowed:
            return JSONResponse({'detail':'Authentication required'},status_code=401,headers={'WWW-Authenticate':'Basic realm="Building Brain"'})
        return await call_next(request)

app.mount('/static',StaticFiles(directory=BASE/'static'),name='static')

class PropertyIn(BaseModel):
    name:str=Field(min_length=2,max_length=120)
    description:str=Field(default='',max_length=500)
class BuildingIn(BaseModel):
    property_id:int
    name:str=Field(min_length=1,max_length=120)
    template_id:int|None=None
class AssetIn(BaseModel):
    property_id:int
    building_id:int
    name:str=Field(min_length=2,max_length=120)
    system:str=Field(default='',max_length=80)
    location:str=Field(default='',max_length=200)
    model:str=Field(default='',max_length=120)
    serial:str=Field(default='',max_length=120)
    notes:str=Field(default='',max_length=3000)
    warranty_until:str=Field(default='',max_length=30)
class NoteIn(BaseModel):
    property_id:int
    building_id:int
    title:str=Field(min_length=2,max_length=150)
    body:str=Field(min_length=5,max_length=5000)
    author:str=Field(min_length=1,max_length=80)
class ExceptionIn(BaseModel):
    property_id:int
    building_id:int
    label:str=Field(min_length=2,max_length=150)
    details:str=Field(min_length=5,max_length=5000)
    author:str=Field(min_length=1,max_length=80)
class ReviewIn(BaseModel):
    status:str
class AskIn(BaseModel):
    property_id:int
    building_id:int|None=None
    question:str=Field(min_length=3,max_length=500)

def not_found(exc):
    raise HTTPException(status_code=404,detail=str(exc))

@app.get('/')
def index():
    return FileResponse(BASE/'static'/'index.html')

@app.get('/healthz')
def health():
    return {'ok':True}

@app.get('/api/overview')
def overview():
    with db() as con:
        p=[dict(x) for x in con.execute('SELECT * FROM properties ORDER BY name')]
        b=[dict(x) for x in con.execute('SELECT * FROM buildings ORDER BY name')]
        stats={name:one(con,f'SELECT COUNT(*) AS total FROM {name}')['total'] for name in ('properties','buildings','documents','assets','field_notes','exceptions')}
        stats['pending_reviews']=one(con,"SELECT (SELECT count(*) FROM field_notes WHERE status='pending') + (SELECT count(*) FROM exceptions WHERE status='pending') AS total")['total']
        return {'properties':p,'buildings':b,'stats':stats,'ai_mode':os.getenv('AI_PROVIDER','none')}

@app.post('/api/properties',status_code=201)
def add_property(item:PropertyIn):
    with db() as con:
        id=con.execute('INSERT INTO properties(name,description) VALUES (?,?)',(item.name.strip(),item.description.strip())).lastrowid
        return rowdict(one(con,'SELECT * FROM properties WHERE id=?',(id,)))

@app.post('/api/buildings',status_code=201)
def add_building(item:BuildingIn):
    with db() as con:
        try:
            ensure_property(con,item.property_id)
            if item.template_id is not None:
                ensure_building(con,item.property_id,item.template_id)
        except LookupError as exc: not_found(exc)
        if one(con,'SELECT 1 FROM buildings WHERE property_id=? AND name=?',(item.property_id,item.name.strip())):
            raise HTTPException(409,'Building already exists in this property')
        id=con.execute('INSERT INTO buildings(property_id,name,template_id) VALUES (?,?,?)',(item.property_id,item.name.strip(),item.template_id)).lastrowid
        return rowdict(one(con,'SELECT * FROM buildings WHERE id=?',(id,)))

@app.get('/api/documents')
def list_documents(property_id:int,building_id:int|None=None):
    with db() as con:
        try: ensure_property(con,property_id)
        except LookupError as exc: not_found(exc)
        if building_id is not None:
            try: ensure_building(con,property_id,building_id)
            except LookupError as exc: not_found(exc)
        sql='SELECT d.*, b.name AS building_name FROM documents d LEFT JOIN buildings b ON d.building_id=b.id WHERE d.property_id=?'
        args=[property_id]
        if building_id is not None:
            building=ensure_building(con,property_id,building_id)
            accessible=[building_id]
            if building['template_id'] is not None:
                accessible.append(building['template_id'])
            sql+=' AND (d.building_id IS NULL OR d.building_id IN ('+','.join('?' for _ in accessible)+'))'
            args+=accessible
        return [dict(r) for r in con.execute(sql+' ORDER BY d.created_at DESC,d.id DESC',args)]

@app.post('/api/documents/upload',status_code=201)
async def upload_document(property_id:int=Form(...),building_id:str=Form(''),file:UploadFile=File(...)):
    filename=Path((file.filename or '').replace('\\','/')).name.strip()
    if not filename or Path(filename).suffix.lower() not in SUPPORTED:
        raise HTTPException(422,'Upload a PDF, DOCX, TXT, MD, or CSV file.')
    data=await file.read(MAX_BYTES+1)
    if not data or len(data)>MAX_BYTES:
        raise HTTPException(413,'File must be nonempty and <= 20 MB.')
    try:
        bid=int(building_id) if building_id else None
    except ValueError:
        raise HTTPException(422,'Invalid building_id')
    try:
        texts,pages=extract(filename,data)
    except IngestError as exc:
        raise HTTPException(422,str(exc))
    sha=hashlib.sha256(data).hexdigest()
    with db() as con:
        try:
            ensure_property(con,property_id)
            if bid is not None:ensure_building(con,property_id,bid)
        except LookupError as exc: not_found(exc)
        prior=one(con,'SELECT id FROM documents WHERE property_id=? AND building_id IS ? AND sha256=?',(property_id,bid,sha))
        if prior:
            raise HTTPException(409,f'This file is already indexed as document #{prior["id"]}.')
        doc_id=con.execute('INSERT INTO documents(property_id,building_id,filename,kind,sha256,size_bytes,pages) VALUES (?,?,?,?,?,?,?)',
            (property_id,bid,filename,Path(filename).suffix.lower(),sha,len(data),pages)).lastrowid
        count=0
        for page,text in texts:
            for i,part in enumerate(chunks(text)):
                con.execute('INSERT INTO chunks(property_id,building_id,document_id,source_type,page_number,chunk_index,body) VALUES (?,?,?,?,?,?,?)',
                    (property_id,bid,doc_id,'document',page,i,part))
                count+=1
        if not count:
            raise HTTPException(422,'No readable text to index')
        folder=database_path().parent/'uploads'/str(doc_id)
        folder.mkdir(parents=True,exist_ok=True)
        (folder/filename).write_bytes(data)
        return {'id':doc_id,'filename':filename,'chunks':count,'pages':pages,'building_id':bid}

@app.get('/api/documents/{doc_id}/file')
def get_document_file(doc_id:int):
    with db() as con:
        row=one(con,'SELECT * FROM documents WHERE id=?',(doc_id,))
        if not row:raise HTTPException(404,'Document not found')
        path=database_path().parent/'uploads'/str(doc_id)/row['filename']
        if not path.is_file(): raise HTTPException(404,'Original file missing')
        return FileResponse(path,filename=row['filename'])

@app.delete('/api/documents/{doc_id}')
def delete_document(doc_id:int):
    with db() as con:
        row=one(con,'SELECT * FROM documents WHERE id=?',(doc_id,))
        if not row:raise HTTPException(404,'Document not found')
        remove_chunks(con,document_id=doc_id)
        con.execute('DELETE FROM documents WHERE id=?',(doc_id,))
    path=database_path().parent/'uploads'/str(doc_id)/row['filename']
    path.unlink(missing_ok=True)
    try:path.parent.rmdir()
    except OSError:pass
    return {'deleted':doc_id}

@app.get('/api/assets')
def list_assets(property_id:int,building_id:int|None=None):
    with db() as con:
        try:ensure_property(con,property_id)
        except LookupError as exc:not_found(exc)
        template_id=None
        if building_id is not None:
            try: b=ensure_building(con,property_id,building_id)
            except LookupError as exc:not_found(exc)
            template_id=b['template_id']
        sql='SELECT a.*,b.name AS building_name FROM assets a JOIN buildings b ON a.building_id=b.id WHERE a.property_id=?'
        args=[property_id]
        if building_id is not None:
            allowed=[building_id]+([template_id] if template_id else [])
            sql+=' AND a.building_id IN ('+','.join('?' for _ in allowed)+')'
            args+=allowed
        rows=[dict(r) for r in con.execute(sql+' ORDER BY a.name',args)]
        for r in rows:
            r['inherited']=bool(template_id and r['building_id']==template_id)
        return rows

@app.post('/api/assets',status_code=201)
def add_asset(item:AssetIn):
    with db() as con:
        try:ensure_building(con,item.property_id,item.building_id)
        except LookupError as exc:not_found(exc)
        id=con.execute('INSERT INTO assets(property_id,building_id,name,system,location,model,serial,notes,warranty_until) VALUES (?,?,?,?,?,?,?,?,?)',
            (item.property_id,item.building_id,item.name.strip(),item.system,item.location,item.model,item.serial,item.notes,item.warranty_until)).lastrowid
        blob='\n'.join([f'Equipment: {item.name}',f'System: {item.system}',f'Location: {item.location}',f'Model: {item.model}',f'Serial: {item.serial}',f'Maintenance notes: {item.notes}',f'Warranty until: {item.warranty_until}'])
        con.execute("INSERT INTO chunks(property_id,building_id,asset_id,source_type,body) VALUES (?,?,?,'asset',?)",(item.property_id,item.building_id,id,blob))
        return rowdict(one(con,'SELECT * FROM assets WHERE id=?',(id,)))

@app.get('/api/notes')
def list_notes(property_id:int,building_id:int|None=None):
    return _list_reviewable('field_notes',property_id,building_id)
@app.post('/api/notes',status_code=201)
def add_note(item:NoteIn):
    return _add_reviewable('field_notes',item)
@app.post('/api/notes/{item_id}/review')
def review_note(item_id:int,payload:ReviewIn):
    return _review('field_notes',item_id,payload.status)
@app.get('/api/exceptions')
def list_exceptions(property_id:int,building_id:int|None=None):
    return _list_reviewable('exceptions',property_id,building_id)
@app.post('/api/exceptions',status_code=201)
def add_exception(item:ExceptionIn):
    return _add_reviewable('exceptions',item)
@app.post('/api/exceptions/{item_id}/review')
def review_exception(item_id:int,payload:ReviewIn):
    return _review('exceptions',item_id,payload.status)

def _list_reviewable(table,property_id,building_id):
    assert table in ('field_notes','exceptions')
    with db() as con:
        try:ensure_property(con,property_id)
        except LookupError as exc:not_found(exc)
        sql=f'SELECT t.*,b.name AS building_name FROM {table} t JOIN buildings b ON t.building_id=b.id WHERE t.property_id=?'
        args=[property_id]
        if building_id is not None:
            try:ensure_building(con,property_id,building_id)
            except LookupError as exc:not_found(exc)
            sql+=' AND t.building_id=?'
            args.append(building_id)
        return [dict(r) for r in con.execute(sql+' ORDER BY t.id DESC',args)]

def _add_reviewable(table,item):
    assert table in ('field_notes','exceptions')
    with db() as con:
        try:ensure_building(con,item.property_id,item.building_id)
        except LookupError as exc:not_found(exc)
        if table=='field_notes':
            sql='INSERT INTO field_notes(property_id,building_id,title,body,author) VALUES (?,?,?,?,?)'
            values=(item.property_id,item.building_id,item.title,item.body,item.author)
        else:
            sql='INSERT INTO exceptions(property_id,building_id,label,details,author) VALUES (?,?,?,?,?)'
            values=(item.property_id,item.building_id,item.label,item.details,item.author)
        id=con.execute(sql,values).lastrowid
        return rowdict(one(con,f'SELECT * FROM {table} WHERE id=?',(id,)))

def _review(table,item_id,status):
    assert table in ('field_notes','exceptions')
    if status not in ('approved','rejected'):
        raise HTTPException(422,'Review must be approved or rejected')
    with db() as con:
        row=one(con,f'SELECT * FROM {table} WHERE id=?',(item_id,))
        if not row:raise HTTPException(404,'Item not found')
        fk='note_id' if table=='field_notes' else 'exception_id'
        remove_chunks(con,**{fk:item_id})
        con.execute(f'UPDATE {table} SET status=?,reviewed_at=datetime("now") WHERE id=?',(status,item_id))
        if status=='approved':
            title=row['title'] if table=='field_notes' else row['label']
            body=row['body'] if table=='field_notes' else row['details']
            kind='Verified technician field note' if table=='field_notes' else 'Documented building exception (overrides template when applicable)'
            for idx,part in enumerate(chunks(f'{kind}: {title}\n{body}')):
                con.execute(f"INSERT INTO chunks(property_id,building_id,{fk},source_type,chunk_index,body) VALUES (?,?,?,?,?,?)",
                            (row['property_id'],row['building_id'],item_id,'note' if table=='field_notes' else 'exception',idx,part))
        return rowdict(one(con,f'SELECT * FROM {table} WHERE id=?',(item_id,)))

@app.post('/api/ask')
def ask(item:AskIn):
    with db() as con:
        try:matches=search(con,property_id=item.property_id,building_id=item.building_id,question=item.question)
        except LookupError as exc:not_found(exc)
    answer,mode,ai_error=ask_llm(item.question,matches)
    citations=[{'reference':m['reference'],'document_id':m['document_id'],'source_label':m['source_label'],
                'source_type':m['source_type'],'page_number':m['page_number'],'scope':m['scope'],
                'building_name':m['building_name'],'excerpt':m['body'],'asset_id':m['asset_id'],
                'note_id':m['note_id'],'exception_id':m['exception_id']} for m in matches]
    return {'answer':answer,'mode':mode,'citations':citations,'ai_error':ai_error,
            'safety_note':'Confirm current conditions and approved procedures before acting. AI or indexed documents are not a substitute for authorized safety practices.'}
