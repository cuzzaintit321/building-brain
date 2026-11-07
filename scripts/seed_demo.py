"""Optional synthetic demo. Never uses real properties, infrastructure or safety instructions.
Usage (inside app container): python scripts/seed_demo.py
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.db import initialize,db,one
from app.ingest import chunks

def main():
    initialize()
    with db() as con:
        if one(con,'SELECT COUNT(*) AS n FROM properties')['n']:
            print('Database is not empty. Demo seed skipped to protect existing data.')
            return
        prop=con.execute('INSERT INTO properties(name,description) VALUES (?,?)',('Harborview Apartments (DEMO)','Fictional training property only — do not use for actual building work.')).lastrowid
        a=con.execute('INSERT INTO buildings(property_id,name) VALUES (?,?)',(prop,'Building A (Reference)')).lastrowid
        b=con.execute('INSERT INTO buildings(property_id,name,template_id) VALUES (?,?,?)',(prop,'Building B (Inherits A)',a)).lastrowid
        refs=[(None,'DEMO - Property maintenance index.txt',"DEMONSTRATION ONLY. Fictional layout. Do not act on any details on a real property.\nProperty: Harborview Apartments. Facilities Office stores the latest verified drawings. Main water isolation point, for the fictional DEMO scenario, is marked MW-01 on drawing P-001 in Utility Room U-1. Confirm actual valve ID, location, and authorization onsite before doing any work. Emergency contact is the property's designated supervisor."),
              (a,'DEMO - Building A equipment register.txt',"DEMONSTRATION ONLY. Fictional building and fictional equipment.\nBuilding A rooftop unit RTU-A3 serves units 301 through 304. RTU-A3 equipment label lists model HVA-4420 and serial DEMO-02243. The equipment disconnect is depicted near Roof Stairwell R-2 on illustration E-12. This is synthetic training data, not an as-built or safety procedure.\nThe building's domestic hot water branch schematic P-3 labels a fictional isolation valve V-302-H near the third-floor hallway chase. Actual drawings and field verification are required for real use.")]
        for building_id, filename, body in refs:
            doc=con.execute('INSERT INTO documents(property_id,building_id,filename,kind,sha256,size_bytes,pages) VALUES (?,?,?,?,?,?,?)',(prop,building_id,filename,'.txt','demo-'+filename,len(body.encode()),0)).lastrowid
            file_dir=Path(__import__('os').environ.get('DATA_DIR','./appdata'))/'uploads'/str(doc)
            file_dir.mkdir(parents=True,exist_ok=True)
            (file_dir/filename).write_text(body,encoding='utf-8')
            for i,chunk in enumerate(chunks(body)):
                con.execute("INSERT INTO chunks(property_id,building_id,document_id,source_type,chunk_index,body) VALUES (?,?,?,'document',?,?)",(prop,building_id,doc,i,chunk))
        asset=con.execute('INSERT INTO assets(property_id,building_id,name,system,location,model,serial,notes) VALUES (?,?,?,?,?,?,?,?)',(prop,a,'RTU-A3','HVAC','Fictional Roof, near Stairwell R-2','HVA-4420','DEMO-02243','Fictional demo asset. Verify physical labels on real equipment.')).lastrowid
        con.execute("INSERT INTO chunks(property_id,building_id,asset_id,source_type,body) VALUES (?,?,?,'asset',?)",(prop,a,asset,'DEMO fictional equipment: Rooftop RTU-A3 HVAC. Location fictional Roof Stairwell R-2. Model HVA-4420. Serial DEMO-02243. Not field verified.'))
        exc=con.execute('INSERT INTO exceptions(property_id,building_id,label,details,author,status,reviewed_at) VALUES (?,?,?,?,?,"approved",datetime("now"))',
            (prop,b,'Demo Unit 302 reroute','DEMO ONLY: Unlike reference Building A, the fictional hot-water branch for Unit 302 in Building B was rerouted in an imaginary renovation. DO NOT use the Building A valve location as verified for B. Verify the latest as-built drawings and field markings.','Demo supervisor')).lastrowid
        con.execute("INSERT INTO chunks(property_id,building_id,exception_id,source_type,body) VALUES (?,?,?,'exception',?)",(prop,b,exc,'DEMO documented building exception: Unit 302 hot water line rerouted from Building A reference layout. Building A valve location is not verified for Building B. Check latest fictional as-builts.'))
    print('Synthetic demo data ready. Property: Harborview Apartments (DEMO). No real site data included.')

if __name__=='__main__': main()
