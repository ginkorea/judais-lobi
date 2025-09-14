# core/memory/memory.py
# UnifiedMemory: Manages short-term and long-term memory using SQLite and FAISS.

import sqlite3, json, time, hashlib
from pathlib import Path
from typing import Optional, List, Dict
import numpy as np
import faiss
from openai import OpenAI

# ---- Helpers ----
def now() -> int:
    return int(time.time())

def normalize(vec: np.ndarray) -> np.ndarray:
    vec = vec.astype("float32")
    norm = np.linalg.norm(vec)
    return vec / (norm + 1e-8)

# ---- UnifiedMemory ----
class UnifiedMemory:
    def __init__(self, db_path: Path, model="text-embedding-3-large", debug=False):
        """db_path: SQLite file, model: embedding model (default: 3-large)."""
        self.debug = debug
        self.db_path = Path(db_path)
        if self.debug: print(f"db_path: {self.db_path}")
        self.model = model
        if self.debug: print(f"model: {self.model}")
        self.client = OpenAI()

        # FAISS indexes
        self.long_index = None
        self.rag_index = None
        self.long_id_map: List[int] = []
        self.rag_id_map: List[int] = []

        # Ensure DB and schema

        self._ensure_db()

        self._rebuild_indexes()

    # ----- Schema -----
    def _ensure_db(self):
        with sqlite3.connect(self.db_path) as con:
            con.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS meta(
                k TEXT PRIMARY KEY,
                v TEXT
            );
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
        # model lock on first use
        self._ensure_model_lock()

    def _ensure_model_lock(self):
        with sqlite3.connect(self.db_path) as con:
            cur = con.execute("SELECT v FROM meta WHERE k='embedding_model'")
            row = cur.fetchone()
            if row is None:
                con.execute("INSERT INTO meta(k, v) VALUES('embedding_model', ?)", (self.model,))
            else:
                saved = row[0]
                if saved != self.model:
                    raise RuntimeError(
                        f"Embedding model mismatch.\n"
                        f"DB locked to: {saved}\n"
                        f"Requested:   {self.model}\n"
                        f"Choose the same model or run a migration (re-embed)."
                    )

    # ----- Connection Helper -----
    def _connect(self):
        """Helper to open SQLite connection consistently."""
        return sqlite3.connect(self.db_path)


    # ----- Embedding -----
    def _embed(self, text: str) -> np.ndarray:
        """Embed a text string safely (hard-cut to avoid token overflows)."""
        text = text[:8000]  # defensive cap; chunking should keep us below this anyway
        resp = self.client.embeddings.create(input=text, model=self.model)
        return np.array(resp.data[0].embedding, dtype=np.float32)

    # ----- Short Term -----
    def add_short(self, role: str, content: str):
        with sqlite3.connect(self.db_path) as con:
            con.execute("INSERT INTO short_term(role,content,ts) VALUES(?,?,?)",
                        (role, content, now()))

    def load_short(self, n=20) -> List[Dict]:
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute(
                "SELECT role,content FROM short_term ORDER BY id DESC LIMIT ?",
                (n,)
            ).fetchall()
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
        # Update FAISS
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
                row = con.execute(
                    "SELECT role,content FROM long_term WHERE id=?",
                    (rid,)
                ).fetchone()
                if row:
                    results.append({"role": row[0], "content": row[1]})
        return results

    def purge_long(self):
        with sqlite3.connect(self.db_path) as con:
            con.execute("DELETE FROM long_term")
        self.long_index = None
        self.long_id_map = []

    # ----- RAG helpers -----
    def _hash_file(self, path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    # ----- RAG: search / manage -----
    def search_rag(self, query: str, top_k=6, dir_filter: Optional[str] = None):
        if self.rag_index is None:
            return []
        q = normalize(self._embed(query))
        D, I = self.rag_index.search(q.reshape(1, -1), top_k)

        dir_root = None
        if dir_filter:
            dir_root = str(Path(dir_filter).expanduser().resolve())

        results = []
        with sqlite3.connect(self.db_path) as con:
            for idx in I[0]:
                if idx < 0 or idx >= len(self.rag_id_map):
                    continue
                cid = self.rag_id_map[idx]
                row = con.execute(
                    "SELECT dir,file,chunk_index,content FROM rag_chunks WHERE id=?",
                    (cid,)
                ).fetchone()
                if not row:
                    continue
                d, f, chunk, content = row
                f_abs = str(Path(f).resolve())
                if dir_root and not f_abs.startswith(dir_root + "/") and f_abs != dir_root:
                    continue
                results.append({"dir": d, "file": f_abs, "chunk": chunk, "content": content})
        return results


    def delete_rag(self, target: Path):
        """Delete all chunks from a given file or directory and rebuild FAISS."""
        target = Path(target).expanduser().resolve()
        with sqlite3.connect(self.db_path) as con:
            if target.is_file():
                con.execute("DELETE FROM rag_chunks WHERE file=?", (str(target),))
            else:
                con.execute("DELETE FROM rag_chunks WHERE dir=?", (str(target),))
        self._rebuild_rag_index()

    def overwrite_rag(self, target: Path):
        """Delete existing RAG entries for target, then re-crawl."""
        self.delete_rag(target)
        if target.is_file():
            return self.crawl_file(target)
        else:
            return self.crawl_dir(target)

    def rag_status(self):
        """Return a summary of RAG contents: directories, files, and chunk counts."""
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("""
                SELECT dir, file, COUNT(*) as chunks
                FROM rag_chunks
                GROUP BY dir, file
                ORDER BY dir, file
            """).fetchall()
        status: Dict[str, List[Dict]] = {}
        for d, f, c in rows:
            status.setdefault(d, []).append({"file": f, "chunks": c})
        return status

    # ----- Index Rebuild -----
    def _rebuild_indexes(self):
        self._rebuild_long_index()
        self._rebuild_rag_index()

    def _rebuild_long_index(self):
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT id,embedding FROM long_term").fetchall()
        if not rows:
            self.long_index = None
            self.long_id_map = []
            return
        dim = len(np.frombuffer(rows[0][1], dtype=np.float32))
        self.long_index = faiss.IndexFlatIP(dim)
        self.long_id_map = []
        vecs = []
        for rid, eblob in rows:
            v = normalize(np.frombuffer(eblob, dtype=np.float32))
            vecs.append(v)
            self.long_id_map.append(rid)
        self.long_index.add(np.stack(vecs))

    def _rebuild_rag_index(self):
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute("SELECT id,embedding FROM rag_chunks").fetchall()
        if not rows:
            self.rag_index = None
            self.rag_id_map = []
            return
        dim = len(np.frombuffer(rows[0][1], dtype=np.float32))
        self.rag_index = faiss.IndexFlatIP(dim)
        self.rag_id_map = []
        vecs = []
        for rid, eblob in rows:
            v = normalize(np.frombuffer(eblob, dtype=np.float32))
            vecs.append(v)
            self.rag_id_map.append(rid)
        self.rag_index.add(np.stack(vecs))

    # ----- Adventures -----
    def add_adventure(self, prompt: str, code: str, result: str, mode: str, success: bool):
        """Insert a coding adventure into the adventures table."""
        with sqlite3.connect(self.db_path) as con:
            con.execute(
                "INSERT INTO adventures(prompt,code,result,mode,success,ts) VALUES(?,?,?,?,?,?)",
                (prompt, code, result, mode, int(success), now())
            )

    def list_adventures(self, n: int = 10) -> List[Dict]:
        """Return the last N adventures in chronological order (oldest first)."""
        with sqlite3.connect(self.db_path) as con:
            rows = con.execute(
                "SELECT prompt,code,result,mode,success,ts FROM adventures ORDER BY id DESC LIMIT ?",
                (n,)
            ).fetchall()
        # reverse so oldest → newest
        return [
            {
                "prompt": r[0],
                "code": r[1],
                "result": r[2],
                "mode": r[3],
                "success": bool(r[4]),
                "ts": r[5],
            }
            for r in reversed(rows)
        ]



