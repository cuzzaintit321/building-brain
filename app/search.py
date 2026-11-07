"""Property-scoped, citable full-text retrieval with explicit inherited-building labels."""
from __future__ import annotations
import re
from .db import ensure_building, ensure_property

STOPWORDS={'a','an','and','are','at','be','for','from','how','i','in','is','it','me','my','of','on','or','our','please','show','some','tell','that','the','there','these','this','to','us','was','what','where','which','who','why','will','with','you'}

def search(con, *, property_id:int, building_id:int|None, question:str, limit:int=6):
    ensure_property(con, property_id)
    template_id=None
    if building_id is not None:
        b=ensure_building(con,property_id,building_id)
        template_id=b['template_id']
    # Keep identifiers like RTU-A3 or MRS-55 as *phrases*. Splitting them into
    # unrelated OR tokens can misleadingly match the wrong equipment model.
    raw_terms=re.findall(r'[a-z0-9]+(?:[-/][a-z0-9]+)*',question.lower())
    terms=list(dict.fromkeys(t for t in raw_terms if len(t)>=2 and t not in STOPWORDS))[:14]
    if not terms:
        return []
    expr=' OR '.join('"'+t.replace('-', ' ').replace('/', ' ')+'"' for t in terms)
    # A wrong asset ID can be dangerous. If a question names a specific code,
    # never return a passage that only matched generic words like 'model'.
    codes=[t for t in terms if ('-' in t or '/' in t) and any(ch.isdigit() for ch in t)]
    normalize=lambda s: re.sub(r'[^a-z0-9]', '', s.lower())
    condition='c.property_id=?'
    args=[expr,property_id]
    if building_id is not None:
        allowed=[building_id]
        if template_id is not None:
            allowed.append(template_id)
        condition+=' AND (c.building_id IS NULL OR c.building_id IN ('+','.join('?' for _ in allowed)+'))'
        args+=allowed
    args.append(max(1,min(limit,20)))
    rows=con.execute(f"""
      SELECT c.*, d.filename AS document_name, a.name AS asset_name,
             n.title AS note_title, e.label AS exception_label,
             b.name AS building_name, bm25(chunk_fts) AS score
      FROM chunk_fts JOIN chunks c ON c.id=chunk_fts.rowid
      LEFT JOIN documents d ON c.document_id=d.id
      LEFT JOIN assets a ON c.asset_id=a.id
      LEFT JOIN field_notes n ON c.note_id=n.id
      LEFT JOIN exceptions e ON c.exception_id=e.id
      LEFT JOIN buildings b ON c.building_id=b.id
      WHERE chunk_fts MATCH ? AND {condition}
      ORDER BY
        CASE WHEN c.exception_id IS NOT NULL AND c.building_id=? THEN 0
             WHEN c.building_id=? THEN 1
             WHEN c.building_id IS NULL THEN 2 ELSE 3 END,
        bm25(chunk_fts)
      LIMIT ?
    """, args[:-1]+[building_id or -1,building_id or -1,args[-1]]).fetchall()
    results=[]
    for row in rows:
        if codes and not any(normalize(code) in normalize(row['body']) for code in codes):
            continue
        result=dict(row)
        result['reference']=len(results)+1
        result['source_label']=row['document_name'] or row['asset_name'] or row['note_title'] or row['exception_label'] or 'Reference'
        if row['building_id'] is None:
            result['scope']='Property-wide'
        elif building_id is None:
            result['scope']='Building: '+str(row['building_name'])
        elif row['building_id']==building_id:
            result['scope']='This building'
        else:
            result['scope']='Inherited template — confirm on site'
        result['body']=row['body'][:1600]
        results.append(result)
    return results

def excerpts_answer(results):
    if not results:
        return "I couldn't find this in the selected property's indexed references. Upload the relevant drawings or manuals, or ask a different question. Don't infer equipment locations or safety steps from missing documents."
    parts=[]
    for result in results[:3]:
        sample=result['body'].strip().replace('\n',' ')
        if len(sample)>420:
            sample=sample[:420].rsplit(' ',1)[0]+'…'
        parts.append(f"[{result['reference']}] {sample}")
    return 'Relevant source passages (not an AI-generated conclusion):\n\n'+'\n\n'.join(parts)
