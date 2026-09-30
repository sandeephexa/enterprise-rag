"""Offset-preserving chunking and transactional persistent hybrid index storage."""

import hashlib
import json
import re
import sqlite3
import threading
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Protocol

import numpy as np
from numpy.typing import NDArray

from .config import Settings
from .schemas import Answer, Chunk, Document, Generation, Principal, ReviewDecision


def words(text: str) -> list[str]:
    """Unicode-aware tokenization shared by ingestion and keyword retrieval."""
    return re.findall(r"\w+", text.casefold())


class Encoder(Protocol):
    identity: str

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]: ...


class DemoEncoder:
    """Deterministic hashing for offline mechanics tests; NOT semantic embeddings."""

    identity = "demo-hash-v1:256"

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        matrix = np.zeros((len(texts), 256), dtype=np.float32)
        for row, text in enumerate(texts):
            for word in words(text):
                digest = hashlib.sha256(word.encode()).digest()
                matrix[row, int.from_bytes(digest[:2], "big") % 256] += 1
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        return matrix / np.maximum(norms, 1e-12)


class EmbeddingInputTooLong(ValueError):
    """An input cannot be embedded without truncating evidence."""


class SemanticEncoder:
    """Local sentence embedding model; oversized texts fail rather than truncate."""

    def __init__(self, settings: Settings) -> None:
        from sentence_transformers import SentenceTransformer

        self.model = SentenceTransformer(
            settings.embedding_model,
            revision=settings.embedding_revision,
            device=settings.inference_device,
            local_files_only=settings.local_models_only,
            trust_remote_code=False,
        )
        self.identity = f"{settings.embedding_model}@{settings.embedding_revision or 'main'}"
        self.lock = threading.Lock()

    def fits(self, text: str) -> bool:
        """Count actual model tokens, including special tokens, without truncation."""
        with self.lock:
            ids = self.model.tokenizer(text, truncation=False, verbose=False)["input_ids"]
            return len(ids) <= self.model.max_seq_length

    def encode(self, texts: Sequence[str]) -> NDArray[np.float32]:
        with self.lock:
            lengths = self.model.tokenizer(list(texts), truncation=False, verbose=False)[
                "input_ids"
            ]
            if any(len(ids) > self.model.max_seq_length for ids in lengths):
                raise EmbeddingInputTooLong(
                    "Embedding input exceeds model limit; reduce chunk/query length"
                )
            vectors = np.asarray(
                self.model.encode(
                    list(texts),
                    normalize_embeddings=True,
                    show_progress_bar=False,
                ),
                dtype=np.float32,
            )
            if not np.isfinite(vectors).all():
                raise ValueError("Non-finite embeddings")
            return vectors


class Chunker:
    """Pack exact source slices, with bounded overlap and optional semantic boundaries."""

    def __init__(self, settings: Settings, encoder: Encoder) -> None:
        self.settings, self.encoder = settings, encoder

    def _fits(self, text: str) -> bool:
        # Encoders without a context limit (demo and injected adapters) retain char limits.
        fits = getattr(self.encoder, "fits", None)
        return fits(text) if fits is not None else True

    def _fit_end(self, text: str, start: int, end: int) -> int:
        """Shorten an exact source slice to fit the tokenizer, preferring word boundaries."""
        if self._fits(text[start:end]):
            return end
        low, high, best = start + 1, end - 1, start
        while low <= high:
            middle = (low + high) // 2
            if self._fits(text[start:middle]):
                best, low = middle, middle + 1
            else:
                high = middle - 1
        if best == start:
            raise EmbeddingInputTooLong("Embedding token limit cannot fit one source character")
        space = text.rfind(" ", start + (best - start) // 2, best)
        if space > start and self._fits(text[start : space + 1]):
            return space + 1
        return best

    def split(self, document: Document, tenant: str) -> list[Chunk]:
        text, cfg = document.text, self.settings
        pattern = r"\n\s*\n" if cfg.chunk_strategy == "paragraph" else r"(?<=[.!?])\s+|\n+"
        boundaries = [0] + [match.end() for match in re.finditer(pattern, text)] + [len(text)]
        units: list[tuple[int, int]] = []
        for start, end in zip(boundaries, boundaries[1:], strict=False):
            while start < end:
                stop = min(end, start + cfg.chunk_chars)
                if stop < end:
                    space = text.rfind(" ", start + cfg.chunk_chars // 2, stop)
                    if space > start:
                        stop = space + 1
                stop = self._fit_end(text, start, stop)
                units.append((start, stop))
                start = stop
        vectors = (
            self.encoder.encode([text[a:b] for a, b in units])
            if cfg.chunk_strategy == "semantic"
            else None
        )
        spans: list[tuple[int, int]] = []
        start, end = units[0]
        for index, (a, b) in enumerate(units[1:], 1):
            semantic_break = (
                vectors is not None
                and float(vectors[index - 1] @ vectors[index]) < cfg.semantic_break_threshold
            )
            if (
                b - start > cfg.chunk_chars
                or not self._fits(text[start:b])
                or semantic_break
                or cfg.chunk_strategy == "sentence"
            ):
                spans.append((start, end))
                start = a
                # Preserve full new unit; only use overlap if it fits the hard cap.
                if cfg.chunk_strategy != "sentence":
                    overlap_start = max(0, a - min(cfg.overlap_chars, cfg.chunk_chars - (b - a)))
                    # Optional overlap must not make an otherwise valid unit too large.
                    if self._fits(text[overlap_start:b]):
                        start = overlap_start
            end = b
        spans.append((start, end))
        version = hashlib.sha256(document.text.encode()).hexdigest()
        chunks = []
        for start, end in spans:
            while start < end and text[start].isspace():
                start += 1
            while end > start and text[end - 1].isspace():
                end -= 1
            if start == end:
                continue
            key = f"{tenant}:{document.id}:{version}:{start}:{end}"
            chunks.append(
                Chunk(
                    id=hashlib.sha256(key.encode()).hexdigest(),
                    document_id=document.id,
                    version=version,
                    source=document.source,
                    title=document.title,
                    text=text[start:end],
                    start=start,
                    end=end,
                    groups=document.groups,
                )
            )
        return chunks


class DocumentAccessDenied(PermissionError):
    """The principal cannot assign or mutate the document access groups."""


class HybridStore:
    """SQLite vector store + persisted lexical postings for bounded enterprise corpora.

    Exact vector search and BM25 operate on one authorized snapshot. This deliberately
    favors atomicity and auditability over distributed ANN-scale throughput.
    """

    def __init__(self, settings: Settings, encoder: Encoder) -> None:
        self.settings, self.encoder = settings, encoder
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS corpus_versions(tenant TEXT PRIMARY KEY, revision INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks(
                    tenant TEXT NOT NULL, id TEXT NOT NULL, document_id TEXT NOT NULL,
                    payload TEXT NOT NULL, vector BLOB NOT NULL, tokens TEXT NOT NULL,
                    PRIMARY KEY(tenant,id));
                CREATE INDEX IF NOT EXISTS chunks_document ON chunks(tenant,document_id);
                CREATE TABLE IF NOT EXISTS reviews(
                    request_id TEXT PRIMARY KEY, tenant TEXT NOT NULL, groups_json TEXT NOT NULL,
                    payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
                    decision TEXT, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            """)
            db.execute(
                "CREATE INDEX IF NOT EXISTS reviews_tenant_created "
                "ON reviews(tenant,created_at DESC,request_id DESC)"
            )
            identity = "schema-v1:" + encoder.identity
            row = db.execute("SELECT value FROM metadata WHERE key='identity'").fetchone()
            if row and row[0] != identity:
                raise ValueError("Index embedding identity mismatch; rebuild into a new database")
            db.execute("INSERT OR IGNORE INTO metadata VALUES('identity',?)", (identity,))

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.settings.database_path, timeout=2)
        try:
            db.execute("PRAGMA synchronous=FULL")
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, documents: list[Document], principal: Principal) -> int:
        """Build everything before one transaction; failure preserves the previous index."""
        from .guardrails import validate_document

        allowed_groups = set(principal.groups)
        chunker = Chunker(self.settings, self.encoder)
        chunks: list[Chunk] = []
        for document in documents:
            if not set(document.groups).issubset(allowed_groups):
                raise DocumentAccessDenied("Document access denied")
            validate_document(document)
            chunks.extend(chunker.split(document, principal.tenant))
        if not chunks:
            raise ValueError("No indexable content")
        vectors = self.encoder.encode([chunk.text for chunk in chunks])
        if len(vectors) != len(chunks) or not np.isfinite(vectors).all():
            raise ValueError("Invalid embedding batch")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for document in documents:
                self._authorize_mutation(db, document.id, principal)
                db.execute(
                    "DELETE FROM chunks WHERE tenant=? AND document_id=?",
                    (principal.tenant, document.id),
                )
            count = db.execute(
                "SELECT count(*) FROM chunks WHERE tenant=?", (principal.tenant,)
            ).fetchone()[0]
            if count + len(chunks) > self.settings.max_chunks_per_tenant:
                raise ValueError("Tenant index capacity exceeded")
            db.executemany(
                "INSERT INTO chunks VALUES(?,?,?,?,?,?)",
                [
                    (
                        principal.tenant,
                        chunk.id,
                        chunk.document_id,
                        chunk.model_dump_json(),
                        np.asarray(vector, dtype=np.float32).tobytes(),
                        json.dumps(words(chunk.text)),
                    )
                    for chunk, vector in zip(chunks, vectors, strict=True)
                ],
            )
            self._bump_revision(db, principal.tenant)
        return len(chunks)

    @staticmethod
    def _bump_revision(db: sqlite3.Connection, tenant: str) -> None:
        db.execute(
            "INSERT INTO corpus_versions(tenant,revision) VALUES(?,1) "
            "ON CONFLICT(tenant) DO UPDATE SET revision=revision+1",
            (tenant,),
        )

    def revision(self, tenant: str) -> int:
        """Revision changes atomically with supported ingestion/deletion operations."""
        with self.connect() as db:
            row = db.execute(
                "SELECT revision FROM corpus_versions WHERE tenant=?", (tenant,)
            ).fetchone()
        return row[0] if row else 0

    def snapshot(
        self, principal: Principal
    ) -> tuple[list[Chunk], NDArray[np.float32], list[list[str]]]:
        """Filter authorization before either ranking algorithm observes candidates."""
        with self.connect() as db:
            rows = db.execute(
                "SELECT payload,vector,tokens FROM chunks WHERE tenant=? ORDER BY id",
                (principal.tenant,),
            ).fetchall()
        chunks, vectors, tokens = [], [], []
        allowed_groups = set(principal.groups)
        for payload, vector, lexical in rows:
            chunk = Chunk.model_validate_json(payload)
            if allowed_groups.intersection(chunk.groups):
                chunks.append(chunk)
                vectors.append(np.frombuffer(vector, dtype=np.float32))
                tokens.append(json.loads(lexical))
        return chunks, np.stack(vectors) if vectors else np.empty((0, 0), dtype=np.float32), tokens

    @staticmethod
    def _authorize_mutation(db: sqlite3.Connection, document_id: str, principal: Principal) -> None:
        """Require authority over every existing group, within the write transaction."""
        allowed = set(principal.groups)
        rows = db.execute(
            "SELECT payload FROM chunks WHERE tenant=? AND document_id=?",
            (principal.tenant, document_id),
        )
        for (payload,) in rows:
            if not set(json.loads(payload)["groups"]).issubset(allowed):
                raise DocumentAccessDenied("Document access denied")

    def delete(self, document_id: str, principal: Principal) -> int:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            self._authorize_mutation(db, document_id, principal)
            count = db.execute(
                "DELETE FROM chunks WHERE tenant=? AND document_id=?",
                (principal.tenant, document_id),
            ).rowcount
            if count:
                self._bump_revision(db, principal.tenant)
            return count

    def save_review(
        self,
        answer: Answer,
        principal: Principal,
        question: str,
        verified_draft: Generation | None = None,
    ) -> None:
        """Persist only validated output and authorized contexts, never rejected claims."""
        with self.connect() as db:
            db.execute(
                "INSERT INTO reviews(request_id,tenant,groups_json,payload) VALUES(?,?,?,?)",
                (
                    answer.request_id,
                    principal.tenant,
                    json.dumps(principal.groups),
                    json.dumps(
                        {
                            "question": question,
                            "answer": answer.model_dump(),
                            "verified_draft": verified_draft.model_dump()
                            if verified_draft
                            else None,
                            "submitted_by": principal.subject,
                        }
                    ),
                ),
            )

    def reviews(self, principal: Principal) -> list[dict]:
        """Return the newest 100 authorized records without materializing the full queue."""
        allowed = set(principal.groups)
        records = []
        with self.connect() as db:
            rows = db.execute(
                "SELECT request_id,groups_json,payload,state,decision FROM reviews "
                "WHERE tenant=? ORDER BY created_at DESC,request_id DESC",
                (principal.tenant,),
            )
            for rid, groups, payload, state, decision in rows:
                if not set(json.loads(groups)).issubset(allowed):
                    continue
                records.append(
                    {
                        "request_id": rid,
                        "answer": json.loads(payload),
                        "state": state,
                        "decision": json.loads(decision) if decision else None,
                    }
                )
                if len(records) == 100:
                    break
        return records

    def decide(self, request_id: str, decision: ReviewDecision, principal: Principal) -> bool:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT groups_json FROM reviews WHERE request_id=? AND tenant=? AND state='pending'",
                (request_id, principal.tenant),
            ).fetchone()
            if not row or not set(json.loads(row[0])).issubset(principal.groups):
                return False
            db.execute(
                "UPDATE reviews SET state=?,decision=? WHERE request_id=?",
                (
                    decision.decision,
                    json.dumps(
                        {
                            **decision.model_dump(),
                            "reviewed_by": principal.subject,
                            "reviewed_at": datetime.now(UTC).isoformat(),
                        }
                    ),
                    request_id,
                ),
            )
        return True
