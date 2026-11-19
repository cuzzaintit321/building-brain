"""Draft-only building topology capture. No draft is exposed to Ask Brain.
Publishing is deliberately unavailable until individual reviewer identity and
property/specialty authorization are implemented.
"""
import pathlib, secrets
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

System=Literal["Plumbing","Electrical","HVAC","Fire protection","Structural","Building automation","Appliances","General"]
Relation=Literal["feeds","serves","controls","drains_to","connects_to","located_in","monitors","part_of"]

class Evidence(BaseModel):
    source_kind:Literal["field","schematic"]
    source_reference:str=Field(min_length=3,max_length=2000)
    drawing_id:Optional[int]=None
    note_id:Optional[int]=None
    page:Optional[int]=Field(default=None,ge=1)
class Component(Evidence):
    name:str=Field(min_length=1,max_length=180)
    system:System
    component_type:str=Field(min_length=1,max_length=80)
    location:str=Field(default="",max_length=300)
    description:str=Field(default="",max_length=4000)
    asset_id:Optional[int]=None
class Link(Evidence):
    from_id:int
    to_id:int
    relation:Relation
    description:str=Field(default="",max_length=4000)

def install(app,db,auth,uploads,property_exists):
    with db() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS twin_drawings(id INTEGER PRIMARY KEY,property_id INTEGER NOT NULL REFERENCES properties(id),name TEXT NOT NULL,filename TEXT NOT NULL UNIQUE,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS twin_components(id INTEGER PRIMARY KEY,property_id INTEGER NOT NULL REFERENCES properties(id),name TEXT NOT NULL,system TEXT NOT NULL,component_type TEXT NOT NULL,location TEXT NOT NULL,description TEXT NOT NULL,asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,source_kind TEXT NOT NULL,source_reference TEXT NOT NULL,drawing_id INTEGER REFERENCES twin_drawings(id),note_id INTEGER REFERENCES notes(id),page INTEGER,status TEXT NOT NULL DEFAULT 'draft' CHECK(status='draft'),created_at TEXT DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS twin_links(id INTEGER PRIMARY KEY,property_id INTEGER NOT NULL REFERENCES properties(id),from_id INTEGER NOT NULL REFERENCES twin_components(id),to_id INTEGER NOT NULL REFERENCES twin_components(id),relation TEXT NOT NULL,description TEXT NOT NULL,source_kind TEXT NOT NULL,source_reference TEXT NOT NULL,drawing_id INTEGER REFERENCES twin_drawings(id),note_id INTEGER REFERENCES notes(id),page INTEGER,status TEXT NOT NULL DEFAULT 'draft' CHECK(status='draft'),created_at TEXT DEFAULT CURRENT_TIMESTAMP,UNIQUE(property_id,from_id,to_id,relation));
        CREATE INDEX IF NOT EXISTS twin_components_property ON twin_components(property_id);
        CREATE INDEX IF NOT EXISTS twin_links_property ON twin_links(property_id);
        """)
    router=APIRouter(prefix="/api/twin",dependencies=[Depends(auth)])
    def evidence(c,pid,x):
        if not x.source_reference.strip():raise HTTPException(422,"Evidence reference required")
        if x.source_kind=="schematic" and (x.drawing_id is None or x.note_id is not None):raise HTTPException(422,"Select a schematic source")
        if x.source_kind=="field" and (x.drawing_id is not None or x.page is not None):raise HTTPException(422,"Field observations cannot reference a schematic page")
        for table,i in (("twin_drawings",x.drawing_id),("notes",x.note_id)):
            if i is not None and not c.execute(f"SELECT 1 FROM {table} WHERE id=? AND property_id=?",(i,pid)).fetchone():raise HTTPException(404,"Evidence not in selected property")
        return (x.source_kind,x.source_reference.strip(),x.drawing_id,x.note_id,x.page)
    @router.get("")
    def view(property_id:int):
        property_exists(property_id)
        with db() as c:
            out={k:[dict(r) for r in c.execute(f"SELECT * FROM {t} WHERE property_id=? ORDER BY id DESC",(property_id,))] for k,t in (("components","twin_components"),("links","twin_links"))}
            out["drawings"]=[dict(r) for r in c.execute("SELECT id,name,created_at FROM twin_drawings WHERE property_id=? ORDER BY id DESC",(property_id,))]
        return out
    @router.post("/drawings",status_code=201)
    async def upload(property_id:int=Form(...),file:UploadFile=File(...)):
        property_exists(property_id)
        name=pathlib.Path(file.filename or "").name;ext=pathlib.Path(name).suffix.lower()
        data=await file.read(25*1024*1024+1)
        if len(data)>25*1024*1024:raise HTTPException(413,"Maximum schematic size 25 MB")
        valid=(ext==".pdf" and data.startswith(b"%PDF-")) or (ext==".png" and data.startswith(bytes.fromhex("89504e470d0a1a0a"))) or (ext in (".jpg",".jpeg") and data.startswith(bytes.fromhex("ffd8ff")))
        if not valid:raise HTTPException(400,"Use PDF, PNG or JPEG")
        filename="twin-"+secrets.token_hex(16)+ext;path=uploads/filename
        path.write_bytes(data)
        try:
            with db() as c:i=c.execute("INSERT INTO twin_drawings(property_id,name,filename) VALUES(?,?,?)",(property_id,name[:250],filename)).lastrowid
        except Exception:
            path.unlink(missing_ok=True);raise
        return {"id":i}
    @router.get("/drawings/{did}")
    def download(did:int,property_id:int):
        with db() as c:r=c.execute("SELECT * FROM twin_drawings WHERE id=? AND property_id=?",(did,property_id)).fetchone()
        if not r:raise HTTPException(404,"Drawing not found")
        return FileResponse(uploads/r["filename"],filename=r["name"],headers={"X-Content-Type-Options":"nosniff"})
    @router.post("/components",status_code=201)
    def component(property_id:int,x:Component):
        property_exists(property_id)
        if not x.name.strip() or not x.component_type.strip():raise HTTPException(422,"Name and component type required")
        with db() as c:
            if x.asset_id is not None and not c.execute("SELECT 1 FROM assets WHERE id=? AND property_id=?",(x.asset_id,property_id)).fetchone():raise HTTPException(404,"Asset not in property")
            i=c.execute("INSERT INTO twin_components(property_id,name,system,component_type,location,description,asset_id,source_kind,source_reference,drawing_id,note_id,page) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(property_id,x.name.strip(),x.system,x.component_type.strip(),x.location,x.description,x.asset_id)+evidence(c,property_id,x)).lastrowid
        return {"id":i,"status":"draft"}
    @router.post("/links",status_code=201)
    def link(property_id:int,x:Link):
        property_exists(property_id)
        if x.from_id==x.to_id:raise HTTPException(422,"Select two different components")
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            if c.execute("SELECT COUNT(*) FROM twin_components WHERE property_id=? AND id IN (?,?)",(property_id,x.from_id,x.to_id)).fetchone()[0]!=2:raise HTTPException(404,"Components not in property")
            if c.execute("SELECT 1 FROM twin_links WHERE property_id=? AND from_id=? AND to_id=? AND relation=?",(property_id,x.from_id,x.to_id,x.relation)).fetchone():raise HTTPException(409,"Relationship already recorded")
            i=c.execute("INSERT INTO twin_links(property_id,from_id,to_id,relation,description,source_kind,source_reference,drawing_id,note_id,page) VALUES(?,?,?,?,?,?,?,?,?,?)",(property_id,x.from_id,x.to_id,x.relation,x.description)+evidence(c,property_id,x)).lastrowid
        return {"id":i,"status":"draft"}
    app.include_router(router)
