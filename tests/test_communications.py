import importlib
import sys
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(monkeypatch,tmp_path):
    monkeypatch.setenv("DATA_DIR",str(tmp_path))
    monkeypatch.setenv("SECRET_KEY","test-secret-not-production")
    monkeypatch.setenv("ADMIN_PASSWORD","test-password-not-production")
    sys.modules.pop("backend.main",None)
    mod=importlib.import_module("backend.main")
    with TestClient(mod.app) as c:
        assert c.post("/api/login",json={"password":"test-password-not-production"}).status_code==200
        yield c

def account(c,name,p):
    password="test-password-for-"+name
    r=c.post("/api/connect/admin/users",json={"username":name,"password":password,"property_ids":[p]})
    assert r.status_code==200,r.text
    token=c.post("/api/connect/login",json={"username":name,"password":password}).json()["token"]
    return r.json()["id"],{"Authorization":"Bearer "+token}

def test_private_messages_and_call(client):
    c=client
    p=c.post("/api/properties",json={"name":"Shared"}).json()["id"]
    q=c.post("/api/properties",json={"name":"Separate"}).json()["id"]
    a,ha=account(c,"alice",p);b,hb=account(c,"bob",p);z,hz=account(c,"outsider",q)
    base="/api/connect"
    assert c.post(base+"/messages",headers=ha,json={"recipient":b,"body":"Hello"}).status_code==201
    assert c.get(base+f"/messages/{a}",headers=hb).json()[0]["body"]=="Hello"
    assert c.post(base+"/messages",headers=ha,json={"recipient":z,"body":"Denied"}).status_code==404
    r=c.post(base+"/calls",headers=ha,json={"recipient":b,"kind":"video"})
    assert r.status_code==201,r.text
    cid=r.json()["id"]
    route=base+"/calls/"+cid
    assert c.get(route+"/signals",headers=hz).status_code==404
    assert c.post(route+"/signals",headers=ha,json={"kind":"offer","payload":{}}).status_code==409
    assert c.post(route+"/decision",headers=ha,json={"action":"accept"}).status_code==409
    assert c.post(route+"/decision",headers=hb,json={"action":"accept"}).status_code==200
    assert c.post(route+"/signals",headers=ha,json={"kind":"offer","payload":{"type":"offer","sdp":"test"}}).status_code==200
    assert c.get(route+"/signals",headers=hb).json()["signals"][0]["kind"]=="offer"
    assert c.post(route+"/decision",headers=hb,json={"action":"end"}).status_code==200
    assert c.get(base+"/calls",headers=ha).json()==[]
