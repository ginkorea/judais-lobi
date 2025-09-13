# core/memory/rag_utils.py
# Utility functions for reading files and chunking text for RAG.

from pathlib import Path
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
try:
    import docx
except ImportError:
    docx = None

def read_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf" and PdfReader:
        try:
            reader = PdfReader(str(path))
            return "\n".join([p.extract_text() or "" for p in reader.pages])
        except Exception:
            return ""
    if ext == ".docx" and docx:
        try:
            d = docx.Document(str(path))
            return "\n".join([p.text for p in d.paragraphs])
        except Exception:
            return ""
    try:
        return path.read_text(errors="ignore")
    except Exception:
        return ""

def chunk_text(text: str, max_chars=800, overlap=100):
    chunks, buf = [], ""
    for para in text.split("\n\n"):
        if len(buf) + len(para) < max_chars:
            buf += "\n\n" + para
        else:
            if buf.strip():
                chunks.append(buf.strip())
            buf = para
    if buf.strip():
        chunks.append(buf.strip())
    # add simple overlap
    if overlap and len(chunks) > 1:
        out = []
        for i, c in enumerate(chunks):
            if i > 0:
                out.append(chunks[i-1][-overlap:] + "\n" + c)
            else:
                out.append(c)
        return out
    return chunks
