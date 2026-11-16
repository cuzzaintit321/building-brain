import importlib.util
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

@pytest.fixture
def brain(monkeypatch,tmp_path):
    monkeypatch.setenv('DATA_DIR',str(tmp_path))
    monkeypatch.setenv('SECRET_KEY','test-secret-only')
    monkeypatch.setenv('ADMIN_PASSWORD','test-password-only')
    monkeypatch.delenv('OPENAI_API_KEY',raising=False)
    spec=importlib.util.spec_from_file_location('brain_knowledge_test',Path(__file__).resolve().parents[1]/'backend'/'main.py')
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with TestClient(mod.app) as client:
        assert client.post('/api/login',json={'password':'test-password-only'}).status_code==200
        yield client

def new_property(c,name):
    return c.post('/api/properties',json={'name':name}).json()['id']

def lesson(c,p,**overrides):
    payload=dict(brand='ExampleBrand',model='ABC-123',category='Washer',title='Error E25',kind='Error code',content='E25 documented observation alpha',source='Example test manual p. 2',approved=True)
    payload.update(overrides)
    return c.post('/api/knowledge',params={'property_id':p},json=payload)

def ask(c,p,q,asset_id=None):
    return c.post('/api/ask',json={'property_id':p,'question':q,'asset_id':asset_id})

def test_property_isolation_and_draft(brain):
    p=new_property(brain,'A');other=new_property(brain,'B')
    assert lesson(brain,p).status_code==201
    assert lesson(brain,p,title='Draft lesson',approved=False).status_code==201
    assert lesson(brain,other,title='Other property').status_code==201
    r=ask(brain,p,'ABC-123 E25').json()
    assert [s['label'] for s in r['sources'] if s['type']=='knowledge']==['Error E25']
    assert not ask(brain,other,'ExampleBrand E25').json()['sources']

def test_exact_model_and_asset(brain):
    p=new_property(brain,'A')
    assert lesson(brain,p).status_code==201
    assert lesson(brain,p,model='ABC-1234',title='Wrong model').status_code==201
    aid=brain.post('/api/assets',json={'property_id':p,'name':'Washer','category':'Washer','manufacturer':'ExampleBrand','model':'ABC-123'}).json()['id']
    for q,asset in [('ABC-123 E25',None),('E25',aid)]:
        r=ask(brain,p,q,asset).json()
        assert [s['label'] for s in r['sources'] if s['type']=='knowledge']==['Error E25']
    assert ask(brain,new_property(brain,'B'),'E25',aid).status_code==400

def test_approval_requires_source_and_crud(brain):
    p=new_property(brain,'A');other=new_property(brain,'B')
    assert lesson(brain,p,source='').status_code==422
    kid=lesson(brain,p,approved=False,source='').json()['id']
    payload=dict(brand='ExampleBrand',title='Verified',content='Verified observation',source='Manual',approved=True)
    assert brain.put(f'/api/knowledge/{kid}',params={'property_id':other},json=payload).status_code==404
    assert brain.put(f'/api/knowledge/{kid}',params={'property_id':p},json=payload).status_code==200
    assert brain.get('/api/knowledge',params={'property_id':p}).json()[0]['approved']==1
    assert brain.delete(f'/api/knowledge/{kid}',params={'property_id':other}).status_code==404
    assert brain.delete(f'/api/knowledge/{kid}',params={'property_id':p}).status_code==200
    assert brain.get('/api/knowledge',params={'property_id':p}).json()==[]

def test_completed_repairs(brain):
    p=new_property(brain,'A')
    aid=brain.post('/api/assets',json={'property_id':p,'name':'Washer','manufacturer':'ExampleBrand','model':'ABC-123'}).json()['id']
    assert brain.post('/api/orders',json={'property_id':p,'asset_id':aid,'title':'E25 incident','status':'Completed','resolution':'Documented resolution for E25'}).status_code==200
    assert any(s['type']=='repair' for s in ask(brain,p,'E25',aid).json()['sources'])
