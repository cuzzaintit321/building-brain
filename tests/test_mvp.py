from __future__ import annotations
from io import BytesIO
from docx import Document
from pypdf import PdfWriter
from .conftest import property_,building_

def upload(client,p,b,filename,content):
    return client.post('/api/documents/upload',data={'property_id':p,'building_id':str(b) if b else ''},files={'file':(filename,content)})

def ask(client,p,b,q):
    r=client.post('/api/ask',json={'property_id':p,'building_id':b,'question':q})
    assert r.status_code==200,r.text
    return r.json()

def test_health_and_auth(client):
    assert client.get('/healthz').status_code==200
    r=client.get('/',headers={'Authorization':'Basic eDp4'})
    assert r.status_code==401
    assert client.get('/').status_code==200
    assert client.get('/static/app.js').status_code==200

def test_property_scoping_and_pdf_txt_upload(client):
    p1=property_(client,'Harborview')
    p2=property_(client,'Other')
    b1=building_(client,p1)
    b2=building_(client,p2)
    r=upload(client,p1,b1,'manual.txt',b'RTU-A3 model HVA-4417. The isolation valve is V-302-H in Building A.')
    assert r.status_code==201,r.text
    docid=r.json()['id']
    assert client.get(f'/api/documents/{docid}/file').content.startswith(b'RTU-A3')
    r=ask(client,p1,b1,'Where is isolation valve V-302-H?')
    assert len(r['citations'])>0
    assert r['mode']=='search'
    assert r['citations'][0]['source_label']=='manual.txt'
    assert len(ask(client,p2,b2,'Where is isolation valve V-302-H?')['citations'])==0
    assert upload(client,p1,b1,'manual.txt',b'RTU-A3 model HVA-4417. The isolation valve is V-302-H in Building A.').status_code==409
    assert client.delete(f'/api/documents/{docid}').status_code==200
    assert len(ask(client,p1,b1,'V-302-H')['citations'])==0

def test_building_template_inheritance_and_exceptions(client):
    p=property_(client)
    a=building_(client,p)
    b=building_(client,p,'Building B',a)
    c=building_(client,p,'Building C')
    assert upload(client,p,a,'equipment.txt',b'RTU-7 model MRS-44 installed in Building A.').status_code==201
    inherited=ask(client,p,b,'RTU-7 model MRS-44')['citations']
    assert len(inherited)>0
    assert 'Inherited template' in inherited[0]['scope']
    assert ask(client,p,c,'RTU-7')['citations']==[]
    e=client.post('/api/exceptions',json={'property_id':p,'building_id':b,'label':'RTU-7 swapped','details':'RTU-7 was replaced with verified MRS-55 model in Building B.','author':'Tester'})
    assert e.status_code==201
    assert ask(client,p,b,'MRS-55')['citations']==[]
    rev=client.post(f"/api/exceptions/{e.json()['id']}/review",json={'status':'approved'})
    assert rev.status_code==200
    result=ask(client,p,b,'MRS-55')['citations']
    assert result and result[0]['source_type']=='exception'
    assert result[0]['scope']=='This building'

def test_notes_pending_approved_and_rejected(client):
    p=property_(client)
    b=building_(client,p)
    result=client.post('/api/notes',json={'property_id':p,'building_id':b,'title':'Pump location','body':'Demo pump P-33 at the loading platform.','author':'Technician'})
    assert result.status_code==201
    note=result.json()['id']
    assert ask(client,p,b,'loading platform')['citations']==[]
    assert client.post(f'/api/notes/{note}/review',json={'status':'approved'}).status_code==200
    assert ask(client,p,b,'loading platform')['citations'][0]['source_type']=='note'
    assert client.post(f'/api/notes/{note}/review',json={'status':'rejected'}).status_code==200
    assert ask(client,p,b,'loading platform')['citations']==[]

def test_docx_ingestion(client):
    p=property_(client)
    doc=Document(); doc.add_heading('Pump Manual',0);doc.add_paragraph('Valve ZQ-123 is described in this demonstration manual.')
    mem=BytesIO();doc.save(mem)
    result=upload(client,p,None,'pump.docx',mem.getvalue())
    assert result.status_code==201,result.text
    assert ask(client,p,None,'Valve ZQ-123')['citations'][0]['source_label']=='pump.docx'

def test_pdf_without_text_rejected(client):
    p=property_(client)
    pdf=PdfWriter();pdf.add_blank_page(width=612,height=792)
    out=BytesIO();pdf.write(out)
    r=upload(client,p,None,'scanned.pdf',out.getvalue())
    assert r.status_code==422
    assert 'OCR' in r.json()['detail']

def test_reject_invalid_scope_and_types(client):
    p=property_(client)
    other=property_(client,'Property B')
    b=building_(client,other)
    assert client.post('/api/buildings',json={'property_id':p,'name':'Bad','template_id':b}).status_code==404
    assert upload(client,p,b,'manual.txt',b'Physical location of valve V-2.').status_code==404
    assert upload(client,p,None,'script.html',b'<script>bad</script>').status_code==422
    assert client.post('/api/assets',json={'property_id':p,'building_id':b,'name':'Cross account'}).status_code==404


def test_asset_index_and_long_search(client):
    p=property_(client)
    b=building_(client,p)
    r=client.post('/api/assets',json={'property_id':p,'building_id':b,'name':'Pool Pump West','system':'Hydraulics','location':'West equipment room','model':'GX-1000','serial':'AL-47'})
    assert r.status_code==201,r.text
    rows=ask(client,p,b,'Where is the GX-1000 pool pump?')['citations']
    assert rows and rows[0]['source_type']=='asset'
    assert ask(client,p,b,'? ! what is this?')['mode']=='search'

def test_pdf_page_citations(client):
    from reportlab.pdfgen import canvas
    p=property_(client)
    buffer=BytesIO()
    pdf=canvas.Canvas(buffer,pagesize=(612,792))
    pdf.drawString(72,710,'First page - generic information about the property.')
    pdf.showPage()
    pdf.drawString(72,710,'Second page - valve XZ-789 is the inspection demo reference.')
    pdf.showPage();pdf.save()
    result=upload(client,p,None,'reference.pdf',buffer.getvalue())
    assert result.status_code==201,result.text
    assert result.json()['pages']==2
    refs=ask(client,p,None,'valve XZ-789')['citations']
    assert refs and refs[0]['page_number']==2


def test_exact_model_is_not_confused_with_different_model(client):
    p=property_(client)
    b=building_(client,p)
    assert upload(client,p,b,'models.txt',b'RTU-7 uses model MRS-44, not another model.').status_code==201
    assert ask(client,p,b,'Where is model MRS-55?')['citations']==[]
    assert ask(client,p,b,'Where is model MRS-44?')['citations']
