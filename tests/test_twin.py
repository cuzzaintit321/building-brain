from test_property_knowledge import brain, new_property, ask

def component(c,p,name,**overrides):
    data=dict(name=name,system="Plumbing",component_type="valve",source_kind="field",source_reference="Recorded during field walkthrough")
    data.update(overrides)
    return c.post("/api/twin/components",params={"property_id":p},json=data)

def test_drafts_not_retrieved_and_cross_property_links_denied(brain):
    p=new_property(brain,"Twin A")
    other=new_property(brain,"Twin B")
    a=component(brain,p,"Unverified ZetaValve")
    b=component(brain,other,"Other valve")
    assert a.status_code==201 and b.status_code==201
    assert a.json()["status"]=="draft"
    assert not ask(brain,p,"Unverified ZetaValve").json()["sources"]
    x=dict(from_id=a.json()["id"],to_id=b.json()["id"],relation="feeds",source_kind="field",source_reference="Observed")
    assert brain.post("/api/twin/links",params={"property_id":p},json=x).status_code==404
    assert brain.get("/api/twin",params={"property_id":other}).json()["components"][0]["name"]=="Other valve"

def test_schematic_and_auth(brain):
    p=new_property(brain,"Twin A")
    other=new_property(brain,"Twin B")
    assert component(brain,p,"Valve",source_kind="schematic").status_code==422
    d=brain.post("/api/twin/drawings",data={"property_id":p},files={"file":("plan.pdf",b"%PDF-1.4\nexample","application/pdf")})
    assert d.status_code==201
    did=d.json()["id"]
    assert component(brain,other,"Valve",source_kind="schematic",drawing_id=did).status_code==404
    assert component(brain,p,"Valve",source_kind="schematic",drawing_id=did,page=1).status_code==201
    assert brain.get(f"/api/twin/drawings/{did}",params={"property_id":other}).status_code==404
    brain.post("/api/logout")
    assert brain.get("/api/twin",params={"property_id":p}).status_code==401
