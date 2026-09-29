"""Exercise real multipart -> parser process -> vectors -> query, without paid APIs."""

import io
import zipfile

import httpx
import pytest
from defusedxml.common import DefusedXmlException
from openpyxl import Workbook

from rag.app import create_app
from rag.file_parser import ParseError, extract
from rag.schemas import Principal

from .conftest import TOKEN

TEXT = "Enterprise support is available 24 hours a day. Tickets receive a response within 2 hours."


def pdf_bytes(extra_stream: str = "") -> bytes:
    """Small valid PDF with selectable text and a ruled table; no fixture dependency."""
    stream = (
        f"{extra_stream}BT /F1 11 Tf 30 760 Td ({TEXT}) Tj ET\n"
        "BT /F1 11 Tf 40 700 Td (Service) Tj 200 0 Td (Hours) Tj ET\n"
        "BT /F1 11 Tf 40 670 Td (Support) Tj 200 0 Td (24) Tj ET\n"
        "30 720 m 430 720 l 430 650 l 30 650 l h S\n"
        "230 720 m 230 650 l S\n30 685 m 430 685 l S\n"
    ).encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 800 800] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"endstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    offset = len(output)
    output.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for position in offsets[1:]:
        output.extend(f"{position:010} 00000 n \n".encode())
    output.extend(f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{offset}\n%%EOF\n".encode())
    return bytes(output)


def docx_bytes() -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr(
            "_rels/.rels",
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        )
        archive.writestr(
            "word/document.xml",
            f"""<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>{TEXT}</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Support hours</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>24</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>""",
        )
    return output.getvalue()


def xlsx_bytes() -> bytes:
    output = io.BytesIO()
    workbook = Workbook()
    workbook.active.title = "Support"
    workbook.active.append([TEXT])
    workbook.active.append(["Calculated", "=1+1"])
    workbook.create_sheet("Locations").append(["Region", "Europe"])
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def fixture_bytes(extension: str) -> bytes:
    return {
        ".pdf": pdf_bytes,
        ".docx": docx_bytes,
        ".xlsx": xlsx_bytes,
        ".csv": lambda: ("Policy\n" + TEXT + "\n").encode(),
        ".md": lambda: ("# Support policy\n\n" + TEXT).encode(),
        ".txt": lambda: TEXT.encode(),
    }[extension]()


@pytest.mark.parametrize("extension", [".pdf", ".docx", ".xlsx", ".csv", ".md", ".txt"])
async def test_upload_all_formats_to_query(settings, pipeline, principal, extension):
    app = create_app(settings, pipeline, telemetry=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client,
    ):
        response = await client.post(
            "/ingest/file",
            files={
                "file": ("policy" + extension, fixture_bytes(extension), "application/octet-stream")
            },
            data={"groups": '["staff"]'},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["indexed_chunks"] > 0
        assert result["source"].startswith("urn:upload:")
        chunks, vectors, tokens = pipeline.store.snapshot(principal)
        assert len(chunks) == len(vectors) == len(tokens) > 0
        assert TEXT in " ".join(chunk.text for chunk in chunks)
        assert all(chunk.source == result["source"] for chunk in chunks)
        assert not pipeline.store.snapshot(
            Principal(tenant="other", groups=["staff"], roles=["query"])
        )[0]
        query = await client.post("/query", json={"text": "support available hours"})
        assert query.status_code == 200
        assert query.json()["status"] == "answered", query.text
        assert query.json()["citations"]
        if extension == ".xlsx":
            assert any("cached" in warning for warning in result["warnings"])
            assert any("Locations" in chunk.text for chunk in chunks)


@pytest.mark.parametrize(
    ("name", "content", "status"),
    [
        ("test.exe", b"bad", 415),
        ("test.pdf", b"not a PDF", 422),
        ("test.docx", b"not an archive", 422),
        ("test.xlsx", b"not an archive", 422),
        ("test.txt", b"", 422),
        ("test.txt", b"\xff\x00bad", 422),
        ("test.csv", b'"unclosed', 422),
        ("test.md", b" \n ", 422),
    ],
)
async def test_bad_upload_preserves_existing_document(
    settings, pipeline, principal, document, name, content, status
):
    pipeline.store.ingest([document], principal)
    before = pipeline.store.snapshot(principal)[0]
    app = create_app(settings, pipeline, telemetry=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client,
    ):
        response = await client.post(
            "/ingest/file", files={"file": (name, content)}, data={"document_id": document.id}
        )
        assert response.status_code == status, response.text
        assert pipeline.store.snapshot(principal)[0] == before


async def test_limits_auth_metadata_and_atomic_retry(settings, pipeline, principal):
    settings.max_upload_bytes = 1024
    settings.max_extracted_chars = 100
    app = create_app(settings, pipeline, telemetry=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        files = {"file": ("policy.txt", TEXT.encode())}
        assert (await client.get("/ingest/formats")).json()["max_file_bytes"] == 1024
        assert (await client.post("/ingest/file", files=files)).status_code == 401
        client.headers["Authorization"] = "Bearer " + TOKEN
        assert (
            await client.post("/ingest/file", files=files, data={"groups": '["admin"]'})
        ).status_code == 403
        assert (
            await client.post("/ingest/file", files=files, data={"groups": "not-json"})
        ).status_code == 422
        assert (
            await client.post("/ingest/file", files=files, data={"document_id": "../bad"})
        ).status_code == 422
        assert (await client.post("/ingest/file", json={"file": "bad"})).status_code == 415
        assert (
            await client.post("/ingest/file", files={"file": ("big.txt", b"x" * 1025)})
        ).status_code == 413
        assert (
            await client.post("/ingest/file", files={"file": ("big.txt", b"x" * 101)})
        ).status_code == 413
        first = await client.post("/ingest/file", files=files)
        second = await client.post("/ingest/file", files=files)
        assert first.status_code == second.status_code == 200
        assert first.json()["document_id"] == second.json()["document_id"]
        assert len(pipeline.store.snapshot(principal)[0]) == first.json()["indexed_chunks"]


async def test_parse_timeout_reaps_worker_and_cleans_files(
    settings, pipeline, monkeypatch, tmp_path
):
    import rag.uploads as uploads

    settings.upload_parse_timeout_s = 0.00001
    original = uploads.tempfile.TemporaryDirectory
    monkeypatch.setattr(
        uploads.tempfile, "TemporaryDirectory", lambda **kwargs: original(dir=tmp_path, **kwargs)
    )
    app = create_app(settings, pipeline, telemetry=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client,
    ):
        response = await client.post("/ingest/file", files={"file": ("test.txt", TEXT.encode())})
        assert response.status_code == 408
        assert response.json()["detail"]["code"] == "parse_timeout"
        assert not list(tmp_path.glob("rag-upload-*"))


def test_office_entity_and_zip_expansion_rejected(tmp_path):
    path = tmp_path / "bad.docx"
    for xml in [
        b'<!DOCTYPE x [<!ENTITY x SYSTEM "file:///etc/passwd">]><x>&x;</x>',
        b"<x>" + b"a" * 1100000 + b"</x>",
    ]:
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("word/document.xml", xml)
        with pytest.raises((ParseError, DefusedXmlException)):
            extract(path, ".docx", 200000)


def test_page_table_and_office_table_provenance(tmp_path):
    pdf = tmp_path / "table.pdf"
    pdf.write_bytes(pdf_bytes())
    assert 'Page 1, table 1, row 2: ["Support", "24"]' in extract(pdf, ".pdf", 200000)["text"]
    docx = tmp_path / "table.docx"
    docx.write_bytes(docx_bytes())
    assert 'Table row 1: ["Support hours", "24"]' in extract(docx, ".docx", 200000)["text"]


def test_encoding_and_extraction_limit(tmp_path):
    path = tmp_path / "text.txt"
    path.write_bytes("Résumé — engineer".encode("utf-16"))
    assert extract(path, ".txt", 100)["text"] == "Résumé — engineer"
    with pytest.raises(ParseError, match="character limit"):
        extract(path, ".txt", 10)


async def test_index_failure_rolls_back_replacement(
    settings, pipeline, principal, document, monkeypatch
):
    pipeline.store.ingest([document], principal)
    before = pipeline.store.snapshot(principal)[0]
    app = create_app(settings, pipeline, telemetry=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client,
    ):
        # Capacity failure happens after DELETE inside the transaction: old rows must survive.
        settings.max_chunks_per_tenant = 1
        response = await client.post(
            "/ingest/file",
            files={"file": ("replacement.txt", (TEXT * 20).encode())},
            data={"document_id": document.id},
        )
        assert response.status_code == 422
        assert pipeline.store.snapshot(principal)[0] == before

        # Embedding failure occurs before opening the transaction.
        def unavailable(_texts):
            raise RuntimeError("embedding service unavailable")

        monkeypatch.setattr(pipeline.store.encoder, "encode", unavailable)
        response = await client.post(
            "/ingest/file",
            files={"file": ("replacement.txt", TEXT.encode())},
            data={"document_id": document.id},
        )
        assert response.status_code == 503
        assert pipeline.store.snapshot(principal)[0] == before


async def test_upload_stream_and_multipart_limits(settings, pipeline):
    settings.max_upload_bytes = 1024
    app = create_app(settings, pipeline, telemetry=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client,
    ):

        async def oversized_stream():
            for _ in range(70):
                yield b"x" * 1024

        response = await client.post(
            "/ingest/file",
            content=oversized_stream(),
            headers={"Content-Type": "multipart/form-data; boundary=test"},
        )
        assert response.status_code == 413
        duplicate = await client.post(
            "/ingest/file", files=[("file", ("a.txt", b"hello")), ("file", ("b.txt", b"world"))]
        )
        assert duplicate.status_code == 400
        missing = await client.post("/ingest/file", files={"wrong": ("a.txt", b"hello")})
        assert missing.status_code == 422


async def test_embedding_limit_returns_actionable_upload_error(settings, pipeline, monkeypatch):
    from rag.ingestion import EmbeddingInputTooLong

    def too_long(_texts):
        raise EmbeddingInputTooLong("private diagnostic text must not escape")

    monkeypatch.setattr(pipeline.store.encoder, "encode", too_long)
    app = create_app(settings, pipeline, telemetry=False)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client,
    ):
        response = await client.post("/ingest/file", files={"file": ("policy.txt", TEXT.encode())})
        assert response.status_code == 422
        assert response.json()["detail"]["code"] == "embedding_token_limit"
        assert "private diagnostic" not in response.text


def test_pdf_small_word_gaps_remain_readable(tmp_path):
    path = tmp_path / "letter.pdf"
    path.write_bytes(
        pdf_bytes("BT /F1 11 Tf 30 740 Td (18th) Tj 23 0 Td (May) Tj 22.3 0 Td (2024) Tj ET\n")
    )
    assert "18th May 2024" in extract(path, ".pdf", 200000)["text"]
