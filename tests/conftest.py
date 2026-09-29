"""Hermetic test fixtures; live integrations are separately exercised and reported."""

import pytest

from rag.app import build_pipeline
from rag.config import AccessKey, Settings
from rag.schemas import Document, Principal

TOKEN = "test-only-token-with-at-least-24-characters"


@pytest.fixture
def settings(tmp_path):
    return Settings(
        mode="demo",
        generation_evidence_mode="quote",
        answer_style="synthesis",
        database_path=tmp_path / "index.db",
        access_keys=[
            AccessKey(
                token=TOKEN,
                tenant="acme",
                groups=["staff"],
                roles=["query", "ingest", "review"],
            )
        ],
    )


@pytest.fixture
def principal():
    return Principal(tenant="acme", groups=["staff"], roles=["query", "ingest", "review"])


@pytest.fixture
def document():
    return Document(
        id="support",
        title="Support policy",
        source="urn:acme:support",
        text="Enterprise support is available 24 hours a day. Tickets receive a response within 2 hours.",
        groups=["staff"],
    )


@pytest.fixture
async def pipeline(settings):
    service = build_pipeline(settings)
    yield service
    await service.gateway.close()
    service.workers.close()
