"""FacilityGuard: operational CMMS endpoints mounted in the existing Building Brain app.

Single-organization MVP. Authentication is inherited from Building Brain BasicAuthMiddleware.
All work is scoped to a validated existing property, and child references are checked.
"""
from __future__ import annotations
import csv
import io
import sqlite3
from datetime import date, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from .db import db, ensure_property, ensure_building, one

router = APIRouter(prefix='/api/facilityguard', tags=['FacilityGuard'])

SCHEMA = """
CREATE TABLE IF NOT EXISTS fg_work_orders (
 id INTEGER PRIMARY KEY,
 property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
 building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
 asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
 title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
 priority TEXT NOT NULL DEFAULT 'normal' CHECK(priority IN ('low','normal','high','urgent')),
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','in_progress','blocked','completed','cancelled')),
 assigned_to TEXT NOT NULL DEFAULT '', due_date TEXT,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 completed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_fg_wo_scope ON fg_work_orders(property_id,building_id,status,due_date);
CREATE TABLE IF NOT EXISTS fg_pm_plans (
 id INTEGER PRIMARY KEY,
 property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
 building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
 asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
 title TEXT NOT NULL, instructions TEXT NOT NULL DEFAULT '',
 interval_days INTEGER NOT NULL CHECK(interval_days BETWEEN 1 AND 3650),
 next_due TEXT NOT NULL, assigned_to TEXT NOT NULL DEFAULT '',
 active INTEGER NOT NULL DEFAULT 1 CHECK(active IN (0,1)),
 last_completed TEXT,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fg_pm_scope ON fg_pm_plans(property_id,building_id,next_due);
CREATE TABLE IF NOT EXISTS fg_pm_history (
 id INTEGER PRIMARY KEY,
 plan_id INTEGER NOT NULL REFERENCES fg_pm_plans(id) ON DELETE CASCADE,
 completed_on TEXT NOT NULL, performed_by TEXT NOT NULL,
 notes TEXT NOT NULL DEFAULT '',
 work_order_id INTEGER REFERENCES fg_work_orders(id) ON DELETE SET NULL,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS fg_inspections (
 id INTEGER PRIMARY KEY,
 property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
 building_id INTEGER NOT NULL REFERENCES buildings(id) ON DELETE CASCADE,
 asset_id INTEGER REFERENCES assets(id) ON DELETE SET NULL,
 title TEXT NOT NULL, checklist TEXT NOT NULL DEFAULT '',
 due_date TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'scheduled' CHECK(status IN ('scheduled','passed','failed','needs_attention')),
 inspector TEXT NOT NULL DEFAULT '', findings TEXT NOT NULL DEFAULT '',
 completed_at TEXT,
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_fg_inspection_scope ON fg_inspections(property_id,building_id,status,due_date);
"""

def initialize_facilityguard():
    with db() as con:
        con.executescript(SCHEMA)

class Site(BaseModel):
    property_id: int = Field(gt=0)
    building_id: int = Field(gt=0)
    asset_id: int | None = Field(default=None, gt=0)

class WorkOrderIn(Site):
    title: str = Field(min_length=2, max_length=160)
    description: str = Field(default='', max_length=5000)
    priority: Literal['low','normal','high','urgent'] = 'normal'
    assigned_to: str = Field(default='', max_length=100)
    due_date: date | None = None

class WorkOrderUpdate(BaseModel):
    status: Literal['open','in_progress','blocked','completed','cancelled']

class PMIn(Site):
    title: str = Field(min_length=2, max_length=160)
    instructions: str = Field(default='', max_length=5000)
    interval_days: int = Field(ge=1, le=3650)
    next_due: date
    assigned_to: str = Field(default='', max_length=100)

class PMComplete(BaseModel):
    performed_by: str = Field(min_length=1, max_length=100)
    notes: str = Field(default='', max_length=3000)
    completed_on: date = Field(default_factory=date.today)

class InspectionIn(Site):
    title: str = Field(min_length=2, max_length=160)
    checklist: str = Field(default='', max_length=5000)
    due_date: date

class InspectionComplete(BaseModel):
    status: Literal['passed','failed','needs_attention']
    inspector: str = Field(min_length=1, max_length=100)
    findings: str = Field(default='', max_length=5000)
    create_work_order: bool = False


def fail_unknown():
    raise HTTPException(404, 'Record not found in this property')


def verify_site(con, property_id, building_id, asset_id):
    try:
        ensure_building(con, property_id, building_id)
    except LookupError:
        raise HTTPException(404,'Building not found in this property')
    if asset_id is not None and not one(con, 'SELECT id FROM assets WHERE id=? AND property_id=? AND building_id=?', (asset_id,property_id,building_id)):
        raise HTTPException(422,'Asset must belong to the selected building')


def verify_property(con, property_id):
    try: ensure_property(con,property_id)
    except LookupError: raise HTTPException(404,'Property not found')


def row(con, table, record_id, property_id):
    result=one(con, f'SELECT * FROM {table} WHERE id=? AND property_id=?',(record_id,property_id))
    if result is None: fail_unknown()
    return result


def list_scoped(con, table, property_id, building_id, order):
    verify_property(con,property_id)
    args=[property_id]
    where='t.property_id=?'
    if building_id is not None:
        try: ensure_building(con,property_id,building_id)
        except LookupError: raise HTTPException(404,'Building not found in this property')
        where+=' AND t.building_id=?'
        args.append(building_id)
    return [dict(r) for r in con.execute(f'''SELECT t.*,b.name AS building_name,a.name AS asset_name
      FROM {table} t JOIN buildings b ON b.id=t.building_id
      LEFT JOIN assets a ON a.id=t.asset_id AND a.property_id=t.property_id
      WHERE {where} ORDER BY {order}''',args)]

@router.get('/overview')
def overview(property_id:int=Query(gt=0),building_id:int|None=Query(default=None,gt=0)):
    with db() as con:
        verify_property(con,property_id)
        if building_id is not None:
            try:ensure_building(con,property_id,building_id)
            except LookupError:raise HTTPException(404,'Building not found in this property')
        today=date.today().isoformat()
        cond='property_id=?'+(' AND building_id=?' if building_id else '')
        args=(property_id,building_id) if building_id else (property_id,)
        def tally(table, extra='', extra_params=()):
            return con.execute(f'SELECT count(*) FROM {table} WHERE {cond} {extra}',args+extra_params).fetchone()[0]
        return {'work_orders_open':tally('fg_work_orders',"AND status NOT IN ('completed','cancelled')"),
          'work_orders_overdue':tally('fg_work_orders',"AND status NOT IN ('completed','cancelled') AND due_date < ?",(today,)),
          'pm_due':tally('fg_pm_plans','AND active=1 AND next_due <= ?',(today,)),
          'pm_upcoming_7d':tally('fg_pm_plans','AND active=1 AND next_due > ? AND next_due <= ?',(today,(date.today()+timedelta(days=7)).isoformat())),
          'inspections_due':tally('fg_inspections',"AND status='scheduled' AND due_date <= ?",(today,)),
          'inspections_failed':tally('fg_inspections',"AND status IN ('failed','needs_attention')")}

@router.get('/work-orders')
def work_orders(property_id:int=Query(gt=0),building_id:int|None=Query(default=None,gt=0)):
    with db() as con:return list_scoped(con,'fg_work_orders',property_id,building_id,'t.id DESC')

@router.post('/work-orders',status_code=201)
def create_work_order(item:WorkOrderIn):
    with db() as con:
        verify_site(con,item.property_id,item.building_id,item.asset_id)
        ident=con.execute('''INSERT INTO fg_work_orders(property_id,building_id,asset_id,title,description,priority,assigned_to,due_date)
          VALUES(?,?,?,?,?,?,?,?)''',(item.property_id,item.building_id,item.asset_id,item.title.strip(),item.description,item.priority,item.assigned_to,str(item.due_date) if item.due_date else None)).lastrowid
        return dict(row(con,'fg_work_orders',ident,item.property_id))

@router.patch('/work-orders/{record_id}')
def update_work_order(record_id:int,item:WorkOrderUpdate,property_id:int=Query(gt=0)):
    with db() as con:
        old=row(con,'fg_work_orders',record_id,property_id)
        completed=old['completed_at']
        if item.status=='completed' and old['status']!='completed':completed=datetime.now().isoformat(timespec='seconds')
        elif item.status!='completed':completed=None
        con.execute('UPDATE fg_work_orders SET status=?, completed_at=? WHERE id=? AND property_id=?',(item.status,completed,record_id,property_id))
        return dict(row(con,'fg_work_orders',record_id,property_id))

@router.get('/pm-plans')
def pm_plans(property_id:int=Query(gt=0),building_id:int|None=Query(default=None,gt=0)):
    with db() as con:return list_scoped(con,'fg_pm_plans',property_id,building_id,'t.next_due ASC, t.id DESC')

@router.post('/pm-plans',status_code=201)
def create_pm(item:PMIn):
    with db() as con:
        verify_site(con,item.property_id,item.building_id,item.asset_id)
        ident=con.execute('''INSERT INTO fg_pm_plans(property_id,building_id,asset_id,title,instructions,interval_days,next_due,assigned_to)
          VALUES(?,?,?,?,?,?,?,?)''',(item.property_id,item.building_id,item.asset_id,item.title.strip(),item.instructions,item.interval_days,item.next_due.isoformat(),item.assigned_to)).lastrowid
        return dict(row(con,'fg_pm_plans',ident,item.property_id))

@router.post('/pm-plans/{record_id}/complete')
def complete_pm(record_id:int,item:PMComplete,property_id:int=Query(gt=0)):
    with db() as con:
        plan=row(con,'fg_pm_plans',record_id,property_id)
        if not plan['active']:raise HTTPException(409,'PM plan is inactive')
        # Always advance beyond the completion date; retain the due-day cadence when possible.
        next_due=date.fromisoformat(plan['next_due'])
        while next_due<=item.completed_on:
            next_due+=timedelta(days=plan['interval_days'])
        con.execute('INSERT INTO fg_pm_history(plan_id,completed_on,performed_by,notes) VALUES(?,?,?,?)',(record_id,item.completed_on.isoformat(),item.performed_by,item.notes))
        con.execute('UPDATE fg_pm_plans SET next_due=?,last_completed=? WHERE id=? AND property_id=?',(next_due.isoformat(),item.completed_on.isoformat(),record_id,property_id))
        return dict(row(con,'fg_pm_plans',record_id,property_id))

@router.get('/pm-plans/{record_id}/history')
def pm_history(record_id:int,property_id:int=Query(gt=0)):
    with db() as con:
        row(con,'fg_pm_plans',record_id,property_id)
        return [dict(x) for x in con.execute('SELECT * FROM fg_pm_history WHERE plan_id=? ORDER BY id DESC',(record_id,))]

@router.get('/inspections')
def inspections(property_id:int=Query(gt=0),building_id:int|None=Query(default=None,gt=0)):
    with db() as con:return list_scoped(con,'fg_inspections',property_id,building_id,'t.due_date ASC,t.id DESC')

@router.post('/inspections',status_code=201)
def create_inspection(item:InspectionIn):
    with db() as con:
        verify_site(con,item.property_id,item.building_id,item.asset_id)
        ident=con.execute('''INSERT INTO fg_inspections(property_id,building_id,asset_id,title,checklist,due_date)
          VALUES(?,?,?,?,?,?)''',(item.property_id,item.building_id,item.asset_id,item.title.strip(),item.checklist,item.due_date.isoformat())).lastrowid
        return dict(row(con,'fg_inspections',ident,item.property_id))

@router.post('/inspections/{record_id}/complete')
def complete_inspection(record_id:int,item:InspectionComplete,property_id:int=Query(gt=0)):
    with db() as con:
        ins=row(con,'fg_inspections',record_id,property_id)
        if ins['status']!='scheduled':raise HTTPException(409,'Inspection already completed')
        con.execute('''UPDATE fg_inspections SET status=?,inspector=?,findings=?,completed_at=datetime('now')
          WHERE id=? AND property_id=?''',(item.status,item.inspector,item.findings,record_id,property_id))
        linked_wo=None
        if item.create_work_order and item.status in ('failed','needs_attention'):
            linked_wo=con.execute('''INSERT INTO fg_work_orders(property_id,building_id,asset_id,title,description,priority,due_date)
              VALUES (?,?,?,?,?,?,?)''',(property_id,ins['building_id'],ins['asset_id'],f"Resolve: {ins['title']}",item.findings or 'Inspection requires corrective action','high',date.today().isoformat())).lastrowid
        return {'inspection':dict(row(con,'fg_inspections',record_id,property_id)),'created_work_order_id':linked_wo}

@router.get('/report.csv')
def report_csv(property_id:int=Query(gt=0)):
    with db() as con:
        verify_property(con,property_id)
        output=io.StringIO()
        writer=csv.writer(output)
        writer.writerow(['module','id','building','asset','title','status','due_date','assigned_to','details'])
        for table,label in [('fg_work_orders','work_order'),('fg_pm_plans','preventive_maintenance'),('fg_inspections','inspection')]:
            for r in list_scoped(con,table,property_id,None,'t.id DESC'):
                writer.writerow([label,r['id'],r['building_name'],r['asset_name'] or '',r['title'],r.get('status') or ('active' if r.get('active') else 'inactive'),r.get('due_date') or r.get('next_due') or '',r.get('assigned_to') or r.get('inspector') or '',r.get('description') or r.get('instructions') or r.get('findings') or ''])
        data=output.getvalue().encode('utf-8-sig')
        return StreamingResponse(iter([data]),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="facilityguard-property-{property_id}.csv"'})
