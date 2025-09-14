# core/tools/rag_crawler.py
# Manage RAG archive: crawl, overwrite, list, status, delete. Summarize crawls with LLM.

from pathlib import Path
from typing import Optional, List, Dict
from core.tools.tool import Tool
from core.memory.memory import UnifiedMemory
from openai import OpenAI
import faiss, numpy as np, hashlib, time

# optional deps
try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
try:
    import docx
except ImportError:
    docx = None
try:
    import tiktoken
    enc = tiktoken.encoding_for_model("text-embedding-3-large")
except Exception:
    enc = None

def now() -> int: return int(time.time())
def normalize(vec: np.ndarray) -> np.ndarray:
    vec = vec.astype("float32"); return vec / (np.linalg.norm(vec) + 1e-8)

# ---- Local file readers ----
def read_file(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".pdf" and PdfReader:
        try:
            return "\n".join([p.extract_text() or "" for p in PdfReader(str(path)).pages])
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
    # add overlap
    if overlap and len(chunks) > 1:
        out = []
        for i, c in enumerate(chunks):
            if i > 0:
                out.append(chunks[i-1][-overlap:] + "\n" + c)
            else:
                out.append(c)
        return out
    return chunks

def safe_chunk_text(text: str, max_tokens=2000, overlap=200):
    if not text.strip():
        return []
    if not enc:
        return chunk_text(text, max_chars=2000, overlap=200)
    tokens = enc.encode(text)
    step = max_tokens - overlap
    return [enc.decode(tokens[i:i+max_tokens]) for i in range(0, len(tokens), step)]

# ---- Tool ----
class RagCrawlerTool(Tool):
    name = "rag_crawl"
    description = "Manage RAG archive: crawl, overwrite, list, status, delete. Summarize crawls with LLM."

    def __init__(self, memory: UnifiedMemory, model="gpt-5-mini", debug=True):
        super().__init__()
        self.memory = memory
        self.debug = debug
        self.client = OpenAI()
        self.model = model

    # --- low-level helpers ---
    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _embed(self, text: str) -> np.ndarray:
        resp = self.client.embeddings.create(input=text[:8000], model="text-embedding-3-large")
        return np.array(resp.data[0].embedding, dtype=np.float32)

    def _crawl_file(self, file_path: Path):
        """Index a single file into rag_chunks."""
        file_path = Path(file_path).expanduser().resolve()
        if not file_path.is_file():
            return []
        text = read_file(file_path)
        if not text.strip():
            return []

        sha = self._hash_file(file_path)
        file_abs, dir_abs = str(file_path), str(file_path.parent.resolve())
        added_chunks = []

        with self.memory._connect() as con:
            exists = con.execute(
                "SELECT 1 FROM rag_chunks WHERE file=? AND sha=?",
                (file_abs, sha)
            ).fetchone()
            if exists:
                return []

            for i, c in enumerate(safe_chunk_text(text)):
                emb = normalize(self._embed(c))
                cur = con.execute(
                    "INSERT INTO rag_chunks(dir,file,chunk_index,content,embedding,sha,ts) VALUES(?,?,?,?,?,?,?)",
                    (dir_abs, file_abs, i, c, emb.tobytes(), sha, now())
                )
                cid = cur.lastrowid
                if self.memory.rag_index is None:
                    self.memory.rag_index = faiss.IndexFlatIP(len(emb))
                self.memory.rag_index.add(emb.reshape(1, -1))
                self.memory.rag_id_map.append(cid)
                added_chunks.append({"file": file_abs, "chunk": i, "content": c})
        return added_chunks

    # --- main entry point ---
    def __call__(self, action: str, user_message: str = "",
                 dir: Optional[str] = None, file: Optional[str] = None,
                 recursive: bool = False):
        """
        Dispatch archive actions: crawl, overwrite, list, status, delete.
        Adds explicit (Tool used: rag_crawl) markers into short-term memory
        so the LLM can see what just happened.
        """
        tag = "🤖 (Tool used: rag_crawl)"

        if action in ("crawl", "overwrite"):
            if action == "overwrite":
                target = Path(file or dir).expanduser().resolve()
                self.memory.delete_rag(target)

            crawled = []
            if file:
                crawled = self._crawl_file(Path(file))
            elif dir:
                root = Path(dir).expanduser().resolve()
                iterator = root.rglob("*") if recursive else root.glob("*")
                for f in iterator:
                    if f.is_file():
                        crawled.extend(self._crawl_file(f))

            if not crawled:
                msg = f"{tag} No new chunks found for {file or dir}"
                self.memory.add_short("system", msg)
                return {"status": "no new chunks"}

            joined = "\n".join(c["content"] for c in crawled[:10])
            prompt = (
                f"You just {action}d {len(crawled)} chunks from {file or dir}.\n\n"
                f"Summarize the main topics or ideas."
            )
            summary = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt + "\n\nSample:\n" + joined}]
            ).choices[0].message.content.strip()

            reflection = f"{tag} 📚 {action.title()}ed {file or dir}: {summary}"
            self.memory.add_long("system", reflection)
            self.memory.add_short("system", reflection)
            return {"status": action, "chunks": len(crawled), "summary": summary}

        elif action == "list":
            with self.memory._connect() as con:
                cur = con.execute("SELECT DISTINCT dir FROM rag_chunks")
                rows = [r[0] for r in cur.fetchall()]
            reflection = f"{tag} 📚 Archive list: {len(rows)} directories"
            self.memory.add_short("system", reflection)
            return {"status": "list", "dirs": rows}

        elif action == "status":
            status = self.memory.rag_status()
            reflection = f"{tag} 📚 Archive status checked ({len(status)} dirs)."
            self.memory.add_short("system", reflection)
            return {"status": "status", "detail": status}

        elif action == "delete":
            if not (file or dir):
                return {"status": "error", "msg": "delete requires --dir or --file"}
            target = Path(file or dir).expanduser().resolve()
            self.memory.delete_rag(target)
            reflection = f"{tag} 🗑️ Deleted RAG entries for {target}"
            self.memory.add_short("system", reflection)
            return {"status": "delete", "target": str(target)}

        else:
            return {"status": "error", "msg": f"Unknown action: {action}"}
