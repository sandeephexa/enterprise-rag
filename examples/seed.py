"""Seed the configured local index using the first explicitly configured identity."""

import asyncio
import json
from pathlib import Path

from rag.app import build_pipeline
from rag.config import Settings
from rag.schemas import IngestRequest, Principal


async def main():
    settings = Settings()
    key = settings.access_keys[0]
    if "ingest" not in key.roles:
        raise ValueError("First configured identity must have ingest privilege")
    principal = Principal(tenant=key.tenant, groups=key.groups, roles=key.roles)
    pipeline = await asyncio.to_thread(build_pipeline, settings)
    try:
        batch = IngestRequest.model_validate(
            json.loads(Path("examples/documents.json").read_text())
        )
        count = await pipeline.workers.run(
            pipeline.store.ingest, batch.documents, principal, timeout=120
        )
        print(json.dumps({"indexed_chunks": count, "mode": settings.mode}))
    finally:
        await pipeline.gateway.close()
        pipeline.workers.close()


asyncio.run(main())
