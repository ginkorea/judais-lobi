# memory.py

import json
from pathlib import Path
import numpy as np
from openai import OpenAI
import faiss

class LongTermMemory:
    def __init__(self, path=None, model="text-embedding-3-small"):
        self.file = Path(path or Path.home() / ".lobi_longterm.json")
        self.model = model
        self.client = OpenAI()
        self._load()
        self._build_index()

    def _load(self):
        if self.file.exists():
            with open(self.file, "r") as f:
                self.memory = json.load(f)
        else:
            self.memory = []

    def _save(self):
        with open(self.file, "w") as f:
            json.dump(self.memory, f, indent=2)

    def _embed(self, text):
        response = self.client.embeddings.create(
            input=text,
            model=self.model
        )
        return response.data[0].embedding

    def _build_index(self):
        self.index = None
        if not self.memory:
            return

        dim = len(self.memory[0]["embedding"])
        self.index = faiss.IndexFlatIP(dim)
        self.id_map = []
        vectors = []

        for i, entry in enumerate(self.memory):
            vec = np.array(entry["embedding"], dtype=np.float32)
            vec /= np.linalg.norm(vec)  # Normalize for cosine similarity
            vectors.append(vec)
            self.id_map.append(i)

        if vectors:
            self.index.add(np.stack(vectors))

    def add(self, role, content, metadata=None):
        embedding = self._embed(content)
        self.memory.append({
            "role": role,
            "content": content,
            "embedding": embedding,
            "meta": metadata or {}
        })
        self._save()
        self._build_index()

    def purge(self, role_filter=None):
        if role_filter:
            self.memory = [entry for entry in self.memory if entry["role"] != role_filter]
        else:
            self.memory = []
        self._save()
        self._build_index()

    def search(self, query, top_k=3):
        if not self.memory or not self.index:
            return []

        query_vec = np.array(self._embed(query), dtype=np.float32)
        query_vec /= np.linalg.norm(query_vec)
        D, I = self.index.search(np.expand_dims(query_vec, axis=0), top_k)

        results = []
        for idx in I[0]:
            if idx < len(self.id_map):
                entry = self.memory[self.id_map[idx]]
                results.append(entry)
        return results

    def dump_summary(self, limit=5):
        print(f"🧠 Showing first {limit} memory entries:")
        for i, entry in enumerate(self.memory[:limit]):
            preview = entry['content'][:80].replace('\n', ' ')
            role = entry.get("role", "unknown")
            meta = entry.get("meta", {})
            print(f"{i+1}. [{role}] {preview}...  (meta: {meta})")

    @staticmethod
    def _cosine_similarity(v1, v2):
        v1 = np.array(v1, dtype=np.float32)
        v2 = np.array(v2, dtype=np.float32)
        norm_product = np.linalg.norm(v1) * np.linalg.norm(v2)
        if norm_product == 0:
            return 0.0
        return float(np.dot(v1, v2) / norm_product)
