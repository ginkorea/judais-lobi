# core/memory/memory.py
# UnifiedMemory: Manages short-term and long-term memory using SQLite and FAISS.

import sqlite3, json, time, hashlib
from pathlib import Path
from typing import Optional, List, Dict
import numpy as np
import faiss
from openai import OpenAI
from core.memory.rag_utils import read_file, safe_chunk_text

# ---- Helpers ----
def now() -> int:
    return int(time.time())

def normalize(vec: np.ndarray) -> np.ndarray:
    vec = vec.astype("float32")
    norm = np.linalg.norm(vec)
    return vec / (norm + 1e-8)

# ---- UnifiedMemory ----
class UnifiedMemory:
    def __init__(self, db_path: Path, model="text-embedding-3-large"):
        """db_path: SQLite file, model: embedding model (default: 3-large)."""
        self.db_path = Path(db_path)
        self.model = model
        self.client = OpenAI()

        # FAISS indexes
        self.long_index = None
        self.rag_index = None
        self.long_id_map = []
        self.rag_id_map = []

        self._ensure_db()
        self._rebuild_indexes()

    # ----- Schema -----
    def _ensure_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS short_term(
                id INTEGER PRIMARY KEY,
                role TEXT, content TEXT, ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS long_term(
                id INTEGER PRIMARY KEY,
                role TEXT, content TEXT,
                embedding BLOB, meta TEXT, ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS rag_chunks(
                id INTEGER PRIMARY KEY,
                dir TEXT, file TEXT, chunk_index INT,
                content TEXT, embedding BLOB,
                sha TEXT, ts INTEGER
            );
            CREATE TABLE IF NOT EXISTS adventures(
                id INTEGER PRIMARY KEY,
                prompt TEXT, code TEXT, result TEXT,
                mode TEXT, success INT, ts INTEGER
            );
            """)

    # ----- Embedding -----
    def _embed(self, text: str) -> np.ndarray:
        """Embed a text string safely."""
        text = text[:8000]  # hard cutoff just in case
        resp = self.client.embeddings.create(input=text, model=self.model)
        return np.array(resp.data[0].embedding, dtype=np.float32)

    # ----- Short Term -----
    def add_short(self, role: str, content: str):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO short_term(role,content,ts) VALUES(?,?,?)",
                        (role, content, now()))

    def load_short(self, n=20) -> List[Dict]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT role,content FROM short_term ORDER BY id DESC LIMIT ?",
                               (n,)).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def reset_short(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM short_term")

    # ----- Long Term -----
    def add_long(self, role: str, content: str, meta: Optional[dict] = None):
        emb = normalize(self._embed(content))
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute(
                "INSERT INTO long_term(role,content,embedding,meta,ts) VALUES(?,?,?,?,?)",
                (role, content, emb.tobytes(), json.dumps(meta or {}), now())
            )
            rid = cur.lastrowid
        if self.long_index is None:
            self.long_index = faiss.IndexFlatIP(len(emb))
        self.long_index.add(emb.reshape(1, -1))
        self.long_id_map.append(rid)

    def search_long(self, query: str, top_k=3) -> List[Dict]:
        if self.long_index is None:
            return []
        q = normalize(self._embed(query))
        D, I = self.long_index.search(q.reshape(1, -1), top_k)
        results = []
        with sqlite3.connect(self.db_path) as con:
            for idx in I[0]:
                if idx < 0 or idx >= len(self.long_id_map):
                    continue
                rid = self.long_id_map[idx]
                row = con.execute("SELECT role,content FROM long_term WHERE id=?", (rid,)).fetchone()
                if row:
                    results.append({"role": row[0], "content": row[1]})
        return results

    def purge_long(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM long_term")
        self.long_index = None
        self.long_id_map = []

    # ----- RAG -----
    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def crawl_dir(self, dir_path: Path, include: Optional[str] = None, recursive: bool = False):
        dir_path = Path(dir_path).expanduser().resolve()
        added = []
        iterator = dir_path.rglob("*") if recursive else dir_path.glob("*")
        with sqlite3.connect(self.db_path) as con:
            for f in iterator:
                if not f.is_file():
                    continue
                if include and not f.match(include):
                    continue
                text = read_file(f)
                if not text.strip():
                    continue
                sha = self._hash_file(f)
                exists = con.execute("SELECT 1 FROM rag_chunks WHERE file=? AND sha=?",
                                     (str(f), sha)).fetchone()
                if exists:
                    continue
                chunks = safe_chunk_text(text)
                for i, c in enumerate(chunks):
                    emb = normalize(self._embed(c))
                    cur = con.execute(
                        "INSERT INTO rag_chunks(dir,file,chunk_index,content,embedding,sha,ts) VALUES(?,?,?,?,?,?,?)",
                        (str(dir_path), str(f), i, c, emb.tobytes(), sha, now())
                    )
                    cid = cur.lastrowid
                    if self.rag_index is None:
                        self.rag_index = faiss.IndexFlatIP(len(emb))
                    self.rag_index.add(emb.reshape(1, -1))
                    self.rag_id_map.append(cid)
                added.append(f)
        return added

    def search_rag(self, query: str, top_k=6, dir_filter: Optional[str] = None):
        if self.rag_index is None:
            return []
        q = normalize(self._embed(query))
        D, I = self.rag_index.search(q.reshape(1, -1), top_k)
        results = []
        with sqlite3.connect(self.db_path) as con:
            for idx in I[0]:
                if idx < 0 or idx >= len(self.rag_id_map):
                    continue
                cid = self.rag_id_map[idx]
                row = con.execute("SELECT dir,file,chunk_index,content FROM rag_chunks WHERE id=?",
                                  (cid,)).fetchone()
                if not row:
                    continue
                d, f, chunk, content = row
                if dir_filter and not str(f).startswith(str(dir_filter)):
                    continue
                results.append({"dir": d, "file": f, "chunk": chunk, "content": content})
        return results
