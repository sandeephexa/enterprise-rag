"""Dual retrieval, reciprocal-rank fusion, cross-encoding and adaptive context selection."""

import math
import threading
from collections import Counter
from collections.abc import Sequence
from typing import Protocol

import numpy as np

from .config import Settings
from .ingestion import Encoder, HybridStore, words
from .schemas import Hit, Principal


class Ranker(Protocol):
    def score(self, pairs: Sequence[tuple[str, str]]) -> list[float]: ...


class DemoRanker:
    """Lexical overlap only; deliberately marked as a non-neural offline test backend."""

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        return [len(set(words(q)) & set(words(t))) / max(1, len(set(words(q)))) for q, t in pairs]


class CrossEncoderRanker:
    """Neural pair scoring; sigmoid scores are thresholds, not calibrated probabilities."""

    def __init__(self, settings: Settings) -> None:
        import torch
        from sentence_transformers import CrossEncoder

        self.model = CrossEncoder(
            settings.reranker_model,
            revision=settings.reranker_revision,
            device=settings.inference_device,
            activation_fn=torch.nn.Sigmoid(),
            local_files_only=settings.local_models_only,
            trust_remote_code=False,
            max_length=512,
        )
        # Own contiguous parameter storage. On this tested macOS runtime, invoking
        # the pooler with safetensors-backed storage produced NaNs/bus errors;
        # materializing parameters fixed the same model without changing weights.
        with torch.no_grad():
            for parameter in self.model.model.parameters():
                parameter.set_(parameter.detach().clone(memory_format=torch.contiguous_format))
        self.lock = threading.Lock()

    def score(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        with self.lock:
            for query, passage in pairs:
                if len(self.model.tokenizer(query, passage, truncation=False)["input_ids"]) > 512:
                    raise ValueError("Reranking pair exceeds model context")
            scores = np.asarray(self.model.predict(list(pairs), show_progress_bar=False)).reshape(
                -1
            )
            if not np.isfinite(scores).all():
                raise ValueError("Non-finite cross-encoder scores")
            return scores.tolist()


def bm25(query: str, corpus: list[list[str]]) -> list[float]:
    """Okapi BM25 with positive Robertson IDF, k1=1.5 and b=0.75."""
    if not corpus:
        return []
    frequency = Counter(word for doc in corpus for word in set(doc))
    average = sum(map(len, corpus)) / len(corpus) or 1
    scores = []
    for document in corpus:
        counts = Counter(document)
        score = 0.0
        for term in set(words(query)):
            n, tf = frequency[term], counts[term]
            idf = math.log(1 + (len(corpus) - n + 0.5) / (n + 0.5))
            score += idf * tf * 2.5 / (tf + 1.5 * (0.25 + 0.75 * len(document) / average))
        scores.append(score)
    return scores


class HybridRetriever:
    def __init__(
        self, settings: Settings, store: HybridStore, encoder: Encoder, ranker: Ranker
    ) -> None:
        self.settings, self.store, self.encoder, self.ranker = settings, store, encoder, ranker

    def candidates(self, queries: list[str], principal: Principal) -> list[Hit]:
        chunks, vectors, corpus = self.store.snapshot(principal)
        if not chunks:
            return []
        query_vectors = self.encoder.encode(queries)
        if vectors.shape[1] != query_vectors.shape[1]:
            raise ValueError("Index dimension mismatch")
        fusion: Counter[int] = Counter()
        for query, vector in zip(queries, query_vectors, strict=True):
            rankings = [list(vectors @ vector), bm25(query, corpus)]
            for scores in rankings:
                order = sorted(range(len(scores)), key=lambda idx: (-scores[idx], chunks[idx].id))
                for rank, idx in enumerate(
                    [i for i in order if scores[i] > 0][: self.settings.candidate_k], 1
                ):
                    fusion[idx] += 1 / (60 + rank)
        order = sorted(fusion, key=lambda idx: (-fusion[idx], chunks[idx].id))[
            : self.settings.candidate_k
        ]
        return [Hit(chunk=chunks[idx], fusion_score=fusion[idx]) for idx in order]

    def rerank(self, query: str, hits: list[Hit]) -> list[Hit]:
        # A chunk may omit the document subject (for example a person's name).
        # Include its title for relevance ranking, but retain the original text
        # and offsets as the only evidence available to generation/verification.
        scores = self.ranker.score(
            [(query, f"{hit.chunk.title}\n{hit.chunk.text}") for hit in hits]
        )
        if len(scores) != len(hits) or any(not math.isfinite(x) or x < 0 or x > 1 for x in scores):
            raise ValueError("Invalid reranker scores")
        ranked = [
            hit.model_copy(update={"rerank_score": score})
            for hit, score in zip(hits, scores, strict=True)
        ]
        ranked.sort(key=lambda hit: (-(hit.rerank_score or 0), hit.chunk.id))
        if not ranked:
            return []
        threshold = max(
            self.settings.rerank_threshold,
            (ranked[0].rerank_score or 0) * self.settings.rerank_relative_threshold,
        )
        # Never pad K with weak evidence. Zero qualifying passages is a valid result.
        return [hit for hit in ranked if (hit.rerank_score or 0) >= threshold][
            : self.settings.max_top_k
        ]


def token_upper_bound(text: str) -> int:
    """Conservative UTF-8 byte upper bound for byte-level tokenizers, not measured usage."""
    return len(text.encode("utf-8"))


def assemble_context(hits: list[Hit], budget: int) -> list[Hit]:
    """Keep whole passages so source offsets/quotes remain stable; remove heavy overlaps."""
    selected: list[Hit] = []
    used = 0
    for hit in hits:
        chunk = hit.chunk
        duplicate = any(
            other.chunk.document_id == chunk.document_id
            and max(0, min(other.chunk.end, chunk.end) - max(other.chunk.start, chunk.start))
            / min(other.chunk.end - other.chunk.start, chunk.end - chunk.start)
            > 0.7
            for other in selected
        )
        size = token_upper_bound(chunk.text) + 100
        if not duplicate and used + size <= budget:
            selected.append(hit)
            used += size
    return selected
