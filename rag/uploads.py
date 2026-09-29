"""Multipart upload lifecycle with killable parsing and atomic existing ingestion."""

import asyncio
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

from fastapi import HTTPException, Request
from opentelemetry import trace
from starlette.datastructures import UploadFile

from .config import Settings
from .file_parser import EXTENSIONS, MAX_PAGES, MAX_SHEETS
from .schemas import Document, Principal


def fail(status: int, code: str, message: str) -> None:
    raise HTTPException(status, {"code": code, "message": message})


def capabilities(settings: Settings) -> dict:
    return {
        "extensions": list(EXTENSIONS),
        "max_file_bytes": settings.max_upload_bytes,
        "max_extracted_chars": settings.max_extracted_chars,
        "max_pdf_pages": MAX_PAGES,
        "max_excel_sheets": MAX_SHEETS,
        "parse_timeout_s": settings.upload_parse_timeout_s,
    }


async def parse_upload(upload: UploadFile, extension: str, settings: Settings) -> dict:
    """Always close/reap the worker before removing private temporary files."""
    with tempfile.TemporaryDirectory(prefix="rag-upload-") as directory:
        path = Path(directory) / ("document" + extension)
        size = 0
        with path.open("xb") as target:
            os.chmod(path, 0o600)
            while block := await upload.read(1024 * 1024):
                size += len(block)
                if size > settings.max_upload_bytes:
                    fail(413, "file_limit", "File exceeds the server upload limit.")
                target.write(block)
        if size == 0:
            fail(422, "empty_file", "The file is empty.")
        # Credentials are not inherited by document parsers. No shell or Office execution.
        worker = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "rag.file_parser",
            str(path),
            extension,
            str(settings.max_extracted_chars),
            cwd=str(Path(__file__).resolve().parent.parent),
            env={
                key: value
                for key, value in os.environ.items()
                if key in {"PATH", "SYSTEMROOT", "LANG"}
            },
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            try:
                output, _ = await asyncio.wait_for(
                    worker.communicate(), settings.upload_parse_timeout_s
                )
            except TimeoutError:
                fail(
                    408,
                    "parse_timeout",
                    "Parsing exceeded its time limit. Split or simplify the file.",
                )
        finally:
            if worker.returncode is None:
                worker.kill()
            await worker.wait()
        if worker.returncode != 0:
            fail(422, "corrupt_file", "The file parser could not complete.")
        result = json.loads(output)
        if error := result.get("error"):
            fail(413 if error["code"].endswith("limit") else 422, error["code"], error["message"])
        return result


async def upload_document(
    request: Request, settings: Settings, principal: Principal
) -> tuple[Document, list[str]]:
    """Read one file and bounded metadata; tenant identity remains server-owned."""
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data;"):
        fail(415, "multipart_required", "Send a multipart/form-data request with a file field.")
    async with request.form(max_files=1, max_fields=3, max_part_size=65536) as form:
        if set(form) - {"file", "document_id", "title", "groups"} or any(
            len(form.getlist(key)) != 1 for key in form
        ):
            fail(422, "metadata", "Unexpected or duplicate form fields.")
        upload = form.get("file")
        if not isinstance(upload, UploadFile):
            fail(422, "missing_file", "Choose a file to upload.")
        name = (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1]
        if not name or len(name) > 255 or any(ord(char) < 32 for char in name):
            fail(422, "filename", "File name is invalid or too long.")
        extension = Path(name).suffix.lower()
        if extension not in EXTENSIONS:
            fail(
                415, "unsupported_type", "Supported files: PDF, Markdown, XLSX, DOCX, CSV and TXT."
            )
        try:
            groups = json.loads(str(form["groups"])) if "groups" in form else principal.groups
            # Validate metadata before spawning any expensive parser.
            document = Document(
                id=str(
                    form.get("document_id")
                    or "file-" + hashlib.sha256(name.encode()).hexdigest()[:32]
                ),
                title=str(form.get("title") or name[:200]),
                source="urn:upload:" + hashlib.sha256(name.encode()).hexdigest(),
                groups=groups,
                text="pending",
            )
        except (ValueError, TypeError):
            fail(
                422,
                "metadata",
                "Invalid document ID, title or groups. Groups must be a JSON string array.",
            )
        if not set(document.groups).issubset(principal.groups):
            fail(403, "groups", "Document groups must belong to the authenticated identity.")
        with trace.get_tracer(__name__).start_as_current_span(
            "ingest.parse", record_exception=False, set_status_on_exception=False
        ) as span:
            span.set_attribute("document.format", extension)
            result = await parse_upload(upload, extension, settings)
            span.set_attribute("document.characters", len(result["text"]))
        return document.model_copy(update={"text": result["text"]}), result["warnings"]
