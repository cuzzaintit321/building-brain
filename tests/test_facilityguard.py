"""Run against the existing Building Brain TestClient fixture."""
from .conftest import property_, building_


def test_full_facilityguard_workflow(client):
    p=property_(client)
    b=building_(client,p)
    scope={'property_id':p,'building_id':b}
    r=client.post('/api/facilityguard/work-orders',json={**scope,'title':'Inspect chilled water pump','priority':'high'})
    assert r.status_code==201,r.text
    work=r.json()
    assert client.get('/api/facilityguard/overview',params={'property_id':p}).json()['work_orders_open']==1
    assert client.patch(f'/api/facilityguard/work-orders/{work["id"]}',params={'property_id':p},json={'status':'completed'}).json()['completed_at']
    plan=client.post('/api/facilityguard/pm-plans',json={**scope,'title':'Monthly filter change','next_due':'2026-01-01','interval_days':30})
    assert plan.status_code==201,plan.text
    pid=plan.json()['id']
    done=client.post(f'/api/facilityguard/pm-plans/{pid}/complete',params={'property_id':p},json={'performed_by':'Technician','completed_on':'2026-02-10','notes':'Changed filter'})
    assert done.status_code==200,done.text
    assert done.json()['next_due']>'2026-02-10'
    assert len(client.get(f'/api/facilityguard/pm-plans/{pid}/history',params={'property_id':p}).json())==1
    ins=client.post('/api/facilityguard/inspections',json={**scope,'title':'Egress light test','due_date':'2026-01-01','checklist':'Test light'})
    assert ins.status_code==201,ins.text
    iid=ins.json()['id']
    r=client.post(f'/api/facilityguard/inspections/{iid}/complete',params={'property_id':p},json={'status':'needs_attention','inspector':'Jane','findings':'Battery failed','create_work_order':True})
    assert r.status_code==200,r.text
    assert r.json()['created_work_order_id']
    assert client.get('/api/facilityguard/report.csv',params={'property_id':p}).status_code==200


def test_property_isolation_and_validation(client):
    p1=property_(client,'North Property')
    p2=property_(client,'South Property')
    b1=building_(client,p1,'First Building')
    b2=building_(client,p2,'Second Building')
    order=client.post('/api/facilityguard/work-orders',json={'property_id':p1,'building_id':b1,'title':'Fix boiler'})
    assert order.status_code==201
    assert client.patch(f'/api/facilityguard/work-orders/{order.json()["id"]}',params={'property_id':p2},json={'status':'completed'}).status_code==404
    assert client.post('/api/facilityguard/work-orders',json={'property_id':p1,'building_id':b2,'title':'Wrong building'}).status_code==404
    asset=client.post('/api/assets',json={'property_id':p2,'building_id':b2,'name':'HVAC unit'})
    assert asset.status_code==201
    assert client.post('/api/facilityguard/inspections',json={'property_id':p1,'building_id':b1,'asset_id':asset.json()['id'],'title':'Cross property','due_date':'2026-01-01'}).status_code==422
    assert client.get('/api/facilityguard/work-orders',params={'property_id':p2}).json()==[]
