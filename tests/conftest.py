from __future__ import annotations
import base64
import os
import tempfile
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def client(monkeypatch,tmp_path):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('APP_PASSWORD','testing-password')
    monkeypatch.setenv('APP_USER','admin')
    monkeypatch.setenv('AI_PROVIDER','none')
    from app.main import app
    with TestClient(app) as client:
        client.headers['Authorization']='Basic '+base64.b64encode(b'admin:testing-password').decode()
        yield client

def property_(client,name='Property A'):
    r=client.post('/api/properties',json={'name':name})
    assert r.status_code==201,r.text
    return r.json()['id']

def building_(client,prop,name='Building A',template_id=None):
    r=client.post('/api/buildings',json={'property_id':prop,'name':name,'template_id':template_id})
    assert r.status_code==201,r.text
    return r.json()['id']
