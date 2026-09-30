"""Validated configuration; credentials are supplied by environment or a secret manager."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AccessKey(BaseModel):
    """Server-owned identity; clients cannot select tenants or privileges."""

    token: SecretStr
    tenant: str = Field(min_length=1, max_length=100)
    groups: list[str] = Field(default_factory=lambda: ["staff"])
    roles: list[Literal["query", "ingest", "review"]] = Field(default_factory=lambda: ["query"])


class Endpoint(BaseModel):
    """A Responses-compatible endpoint and operator-supplied price schedule."""

    model_config = {"allow_inf_nan": False}

    name: str
    base_url: str = "https://api.openai.com/v1"
    api_key: SecretStr
    model: str
    input_usd_per_million: float = Field(ge=0)
    output_usd_per_million: float = Field(ge=0)

    @model_validator(mode="after")
    def secure_url(self) -> "Endpoint":
        try:
            url = urlsplit(self.base_url)
            port = url.port
        except ValueError as exc:
            raise ValueError("Invalid model endpoint URL") from exc
        if (
            url.scheme != "https"
            or not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or port == 0
        ):
            raise ValueError(
                "Model endpoints require an HTTPS URL without credentials, query or fragment"
            )
        return self


class Settings(BaseSettings):
    """Fail closed on missing production credentials and inconsistent budgets."""

    model_config = SettingsConfigDict(
        env_prefix="RAG_", env_file=".env", extra="ignore", allow_inf_nan=False
    )
    mode: Literal["live", "demo"] = "live"
    database_path: Path = Path("data/rag.sqlite3")
    access_keys: list[AccessKey] = Field(default_factory=list)
    endpoints: list[Endpoint] = Field(default_factory=list)
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"
    embedding_revision: str | None = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
    reranker_model: str = "cross-encoder/ms-marco-MiniLM-L6-v2"
    reranker_revision: str | None = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
    nli_model: str = "cross-encoder/nli-deberta-v3-small"
    nli_revision: str | None = "fa2804872c3b4bd748f38c0185cc85775361e735"
    nli_batch_size: int = Field(default=4, ge=1, le=64)
    nli_entailment_index: int = Field(default=1, ge=0)
    nli_contradiction_index: int = Field(default=0, ge=0)
    local_models_only: bool = False
    inference_device: str = "cpu"
    chunk_strategy: Literal["sentence", "paragraph", "semantic"] = "paragraph"
    chunk_chars: int = Field(default=700, ge=100, le=4000)
    overlap_chars: int = Field(default=80, ge=0)
    semantic_break_threshold: float = Field(default=0.55, ge=-1, le=1)
    max_chunks_per_tenant: int = Field(default=20000, ge=1)
    candidate_k: int = Field(default=30, ge=1, le=100)
    max_top_k: int = Field(default=6, ge=1, le=20)
    rerank_threshold: float = Field(default=0.4, ge=0, le=1)
    rerank_relative_threshold: float = Field(default=0.6, ge=0, le=1)
    entailment_threshold: float = Field(default=0.85, ge=0, le=1)
    contradiction_threshold: float = Field(default=0.2, ge=0, le=1)
    context_token_budget: int = Field(default=5000, ge=500)
    model_context_tokens: int = Field(default=16000, ge=2000)
    answer_style: Literal["extractive", "synthesis"] = "extractive"
    generation_reasoning_effort: (
        Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"] | None
    ) = None
    generation_evidence_mode: Literal["spans", "quote"] = "spans"
    compact_evidence_ids: bool = True
    max_output_tokens: int = Field(default=1500, ge=100)
    latency_budget_s: float = Field(default=20, gt=0)
    rewrite_mode: Literal["fallback", "always", "off"] = "fallback"
    answer_cache_ttl_s: float = Field(default=60, ge=0, le=3600)
    answer_cache_max_entries: int = Field(default=128, ge=1, le=1000)
    rewrite_budget_s: float = Field(default=1.5, gt=0)
    retrieval_budget_s: float = Field(default=3, gt=0)
    guard_budget_s: float = Field(default=3, gt=0)
    endpoint_timeout_s: float = Field(default=6, gt=0)
    retry_attempts: int = Field(default=2, ge=1, le=5)
    max_cost_usd: float = Field(default=0.1, gt=0)
    cpu_workers: int = Field(default=2, ge=1, le=8)
    max_concurrent_requests: int = Field(default=8, ge=1)
    max_body_bytes: int = Field(default=1_000_000, ge=1024)
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1024, le=50 * 1024 * 1024)
    max_extracted_chars: int = Field(default=200000, ge=100, le=200000)
    upload_parse_timeout_s: float = Field(default=30, gt=0, le=60)
    max_concurrent_uploads: int = Field(default=2, ge=1, le=8)
    otlp_endpoint: str | None = None
    service_name: str = "evidence-rag"

    @model_validator(mode="after")
    def coherent(self) -> "Settings":
        if self.overlap_chars >= self.chunk_chars:
            raise ValueError("overlap_chars must be less than chunk_chars")
        if self.max_top_k > self.candidate_k:
            raise ValueError("max_top_k cannot exceed candidate_k")
        if self.context_token_budget + self.max_output_tokens + 1000 > self.model_context_tokens:
            raise ValueError("Context/output budgets leave insufficient prompt overhead")
        if self.guard_budget_s >= self.latency_budget_s:
            raise ValueError("Guard budget must be smaller than request budget")
        if self.mode == "live" and (not self.endpoints or not self.access_keys):
            raise ValueError("Live mode requires RAG_ENDPOINTS and RAG_ACCESS_KEYS")
        if len({key.token.get_secret_value() for key in self.access_keys}) != len(self.access_keys):
            raise ValueError("Access keys must be unique")
        if any(len(key.token.get_secret_value()) < 24 for key in self.access_keys):
            raise ValueError("Use access tokens of at least 24 characters")
        if self.nli_entailment_index == self.nli_contradiction_index:
            raise ValueError("NLI label indices must differ")
        return self
