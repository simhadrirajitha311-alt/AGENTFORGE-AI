import hashlib
import re
from pathlib import PurePath
from typing import Protocol
from uuid import uuid4

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from app.storage import Store


class RelevanceRanker(Protocol):
    def rank(self, query: str, documents: list[str]) -> list[float]: ...


class TfidfRanker:
    """Ranks local chunks by cosine similarity over TF-IDF term features."""

    def rank(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2))
        try:
            matrix = vectorizer.fit_transform([query, *documents])
        except ValueError:
            return [0.0] * len(documents)
        return cosine_similarity(matrix[0:1], matrix[1:]).ravel().tolist()


def chunk_text(text: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    if chunk_size <= 0 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("Require chunk_size > overlap >= 0")
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    chunks = []
    start = 0
    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))
        if end < len(normalized):
            boundary = normalized.rfind(" ", start + chunk_size // 2, end)
            if boundary > start:
                end = boundary
        chunks.append(normalized[start:end].strip())
        if end == len(normalized):
            break
        start = max(end - overlap, start + 1)
    return chunks


class KnowledgeBase:
    def __init__(self, store: Store, ranker: RelevanceRanker | None = None):
        self.store = store
        self.ranker = ranker or TfidfRanker()

    def ingest(self, source_name: str, content: str, max_bytes: int = 1_000_000) -> dict:
        suffix = PurePath(source_name).suffix.lower()
        if suffix not in {".txt", ".md"} or PurePath(source_name).name != source_name:
            raise ValueError("Only plain .txt and .md filenames are accepted")
        encoded = content.encode("utf-8")
        if len(encoded) > max_bytes:
            raise ValueError(f"Document exceeds the {max_bytes} byte limit")
        parts = chunk_text(content)
        if not parts:
            raise ValueError("Document contains no searchable text")
        digest = hashlib.sha256(encoded).hexdigest()
        document_id = str(uuid4())
        chunks = [(str(uuid4()), ordinal, text) for ordinal, text in enumerate(parts)]
        created = self.store.add_document(
            document_id, source_name, digest, {"media_type": "text/markdown" if suffix == ".md" else "text/plain"},
            chunks,
        )
        if not created:
            return {"status": "duplicate", "source_name": source_name, "chunk_count": len(parts)}
        return {"status": "ingested", "document_id": document_id, "source_name": source_name,
                "chunk_count": len(parts)}

    def search(self, query: str, limit: int = 5) -> list[dict]:
        chunks = self.store.list_chunks()
        if not chunks:
            return []
        scores = self.ranker.rank(query, [chunk["text"] for chunk in chunks])
        ranked = sorted(zip(chunks, scores), key=lambda pair: pair[1], reverse=True)
        return [
            {**chunk, "score": round(float(score), 6)}
            for chunk, score in ranked[:limit] if score > 0
        ]
