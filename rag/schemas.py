"""Strict public contracts and structured generation/evaluation schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Principal(StrictModel):
    tenant: str
    groups: list[str]
    roles: list[str]
    subject: str = "system"


class Query(StrictModel):
    text: str = Field(min_length=3, max_length=2000)


class Document(StrictModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,100}$")
    text: str = Field(min_length=1, max_length=200000)
    source: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=200)
    groups: list[str] = Field(min_length=1, max_length=50)


class IngestRequest(StrictModel):
    documents: list[Document] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def unique_ids(self) -> "IngestRequest":
        if len({doc.id for doc in self.documents}) != len(self.documents):
            raise ValueError("Duplicate document IDs in batch")
        return self


class Chunk(StrictModel):
    id: str
    document_id: str
    version: str
    source: str
    title: str
    text: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    groups: list[str]


class Hit(StrictModel):
    chunk: Chunk
    fusion_score: float
    rerank_score: float | None = None


class Evidence(StrictModel):
    chunk_id: str
    quote: str = Field(min_length=1, max_length=2000)


class Claim(StrictModel):
    text: str = Field(min_length=1, max_length=1200)
    evidence: list[Evidence] = Field(min_length=1, max_length=4)


class Generation(StrictModel):
    """The answer has no uncited free-text channel."""

    claims: list[Claim] = Field(max_length=8)
    abstain: bool


class EvidenceSelection(StrictModel):
    """Provider selects source sentences; it cannot invent released answer wording."""

    source_ids: list[str] = Field(max_length=8)
    abstain: bool

    @model_validator(mode="after")
    def consistent(self) -> "EvidenceSelection":
        if self.abstain == bool(self.source_ids):
            raise ValueError("Select sources for an answer, or abstain with no sources")
        return self


class ReferencedClaim(StrictModel):
    """Compact provider-only contract; public claims still carry verified evidence."""

    text: str = Field(min_length=1, max_length=1200)
    source_ids: list[str] = Field(min_length=1, max_length=4)


class ReferencedGeneration(StrictModel):
    claims: list[ReferencedClaim] = Field(max_length=8)
    abstain: bool


class Rewrite(StrictModel):
    queries: list[str] = Field(min_length=1, max_length=2)


class ConflictVerdict(StrictModel):
    """Semantic relationship for one suspected contradiction, not a new answer."""

    pair_id: int = Field(ge=0)
    relation: Literal["compatible", "contradiction", "uncertain"]
    counter_quote: str | None = Field(max_length=4000)
    reason: str = Field(min_length=1, max_length=500)


class ConflictAssessment(StrictModel):
    verdicts: list[ConflictVerdict] = Field(min_length=1, max_length=160)


class Citation(StrictModel):
    number: int
    claim_index: int
    chunk_id: str
    document_id: str
    version: str
    source: str
    title: str
    quote: str
    start: int
    end: int


class Usage(StrictModel):
    input_tokens: int = 0
    output_tokens: int = 0
    known_cost_usd: float = 0
    reserved_cost_usd: float = 0
    uncertain_attempts: int = 0
    attempts: int = 0


class Answer(StrictModel):
    answer_style: Literal["extractive", "synthesis"] = "synthesis"
    initial_verification_reasons: list[str] = Field(default_factory=list)
    cache_hit: bool = False
    request_id: str
    trace_id: str
    status: Literal["answered", "abstained", "review"]
    answer: str
    claims: list[Claim]
    citations: list[Citation]
    contexts: list[Hit]
    review_reasons: list[str]
    faithfulness: float | None
    usage: Usage
    latency_ms: float
    stage_ms: dict[str, float]
    mode: Literal["live", "demo"]


class ReviewDecision(StrictModel):
    decision: Literal["approve", "reject"]
    note: str = Field(min_length=1, max_length=2000)


class EvalCase(StrictModel):
    id: str
    query: Query
    relevant_document_ids: list[str]
    reference_answer: str
    should_abstain: bool = False


class RelevanceJudgment(StrictModel):
    score: float = Field(ge=0, le=1)


class EvalResult(StrictModel):
    id: str
    faithfulness: float | None
    answer_relevance: float | None
    context_precision: float | None
    context_recall: float | None
    success: bool
    latency_ms: float
    known_cost_usd: float
    uncertain_attempts: int
    error: str | None
