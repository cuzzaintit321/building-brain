"""Extract and split supported reference documents into citation-sized passages."""
from __future__ import annotations
import csv
import io
import re
from pathlib import Path
from docx import Document as DocxDocument
from pypdf import PdfReader

MAX_BYTES = 20 * 1024 * 1024
SUPPORTED = {'.pdf', '.docx', '.txt', '.md', '.csv'}

class IngestError(ValueError):
    pass

def chunks(text: str, size: int = 1050, overlap: int = 130):
    text = re.sub(r'\r\n?', '\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text).strip()
    if not text:
        return []
    out=[]
    start=0
    while start < len(text):
        end=min(start + size, len(text))
        if end < len(text):
            cut=max(text.rfind('\n',start+size//2,end), text.rfind('. ',start+size//2,end))
            if cut > start+size//2:
                end=cut+1
        part=text[start:end].strip()
        if part:
            out.append(part)
        if end >= len(text):
            break
        start=max(start+1,end-overlap)
    return out

def extract(filename: str, data: bytes):
    """Return ([(page_number|None, text),...], page_count)."""
    ext=Path(filename).suffix.lower()
    if ext not in SUPPORTED:
        raise IngestError('Supported formats: PDF, DOCX, TXT, MD, CSV. Export CAD/BIM as PDF for the MVP.')
    if not data or len(data)>MAX_BYTES:
        raise IngestError('File must be nonempty and at most 20 MB.')
    try:
        if ext == '.pdf':
            reader=PdfReader(io.BytesIO(data), strict=False)
            if reader.is_encrypted:
                raise IngestError('Encrypted PDFs are not supported.')
            if len(reader.pages)>250:
                raise IngestError('PDF is over the 250-page limit; split it into smaller files.')
            pages=[(i+1,p.extract_text(extraction_mode='plain') or '') for i,p in enumerate(reader.pages)]
            result=[(p,t) for p,t in pages if t.strip()]
            if not result:
                raise IngestError('No selectable text detected. Scan/OCR the PDF before uploading.')
            return result,len(reader.pages)
        if ext == '.docx':
            document=DocxDocument(io.BytesIO(data))
            paragraphs=[p.text for p in document.paragraphs if p.text.strip()]
            for table in document.tables:
                for row in table.rows:
                    paragraphs.append(' | '.join(c.text for c in row.cells))
            result='\n'.join(paragraphs)
            if not result.strip():
                raise IngestError('DOCX contains no readable text.')
            return [(None,result)],0
        text=data.decode('utf-8-sig')
        if ext == '.csv':
            rows=csv.reader(io.StringIO(text))
            text='\n'.join(' | '.join(row) for row in rows)
        if not text.strip():
            raise IngestError('Document contains no readable text.')
        return [(None,text)],0
    except (IngestError,):
        raise
    except Exception as exc:
        raise IngestError(f'Could not read document: {type(exc).__name__}') from exc
