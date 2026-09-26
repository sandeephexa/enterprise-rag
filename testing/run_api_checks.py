"""Start an isolated demo API, assert its contracts, and stop it; no paid API calls."""

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "testing" / "payloads"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("work/testing/api-checks.json"))
    args = parser.parse_args()
    records = []

    def check(name: str, condition: bool) -> None:
        records.append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    config = dotenv_values(ROOT / "testing" / "demo.env")
    keys = json.loads(config["RAG_ACCESS_KEYS"])
    admin, staff, hr, other = [entry["token"] for entry in keys]
    failure = None
    with tempfile.TemporaryDirectory(prefix="rag-api-test-") as temporary:
        env = {key: value for key, value in os.environ.items() if not key.startswith("RAG_")}
        env.update({key: value for key, value in config.items() if value is not None})
        env.update(RAG_DATABASE_PATH=str(Path(temporary) / "test.sqlite3"))
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with (Path(temporary) / "server.log").open("w+") as log:
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "rag.app:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--log-config",
                    "logging.json",
                ],
                cwd=ROOT,
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=10) as client:
                    for _ in range(100):
                        try:
                            if client.get("/health/ready").status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        if process.poll() is not None:
                            raise RuntimeError("Test server exited during startup")
                        time.sleep(0.1)
                    else:
                        raise RuntimeError("Test server did not become ready")

                    def send(method: str, path: str, token: str | None = admin, **kwargs):
                        headers = {"Authorization": f"Bearer {token}"} if token else {}
                        return client.request(method, path, headers=headers, **kwargs)

                    def query(name: str, token: str = admin) -> dict:
                        response = send("POST", "/query", token, json=fixture(name))
                        response.raise_for_status()
                        return response.json()

                    check(
                        "unauthenticated query => 401",
                        send("POST", "/query", None, json=fixture("query-support")).status_code
                        == 401,
                    )
                    check(
                        "query-only identity cannot ingest => 403",
                        send("POST", "/ingest", staff, json=fixture("documents")).status_code
                        == 403,
                    )
                    for name, code in [
                        ("query-invalid", 422),
                        ("query-tenant-spoof", 422),
                        ("query-injection", 400),
                    ]:
                        check(
                            f"{name} => {code}",
                            send("POST", "/query", json=fixture(name)).status_code == code,
                        )
                    check(
                        "oversized body => 413",
                        send("POST", "/query", content=b"x" * 1_000_001).status_code == 413,
                    )
                    check(
                        "injected document => 400",
                        send("POST", "/ingest", json=fixture("document-injection")).status_code
                        == 400,
                    )
                    check("empty-index abstention", query("query-support")["status"] == "abstained")

                    initial = send("POST", "/ingest", json=fixture("documents"))
                    check(
                        "three baseline chunks ingested",
                        initial.status_code == 200 and initial.json()["indexed_chunks"] == 3,
                    )
                    repeated = send("POST", "/ingest", json=fixture("documents"))
                    check(
                        "idempotent reingestion",
                        repeated.status_code == 200 and repeated.json() == initial.json(),
                    )
                    response = send("POST", "/query", staff, json=fixture("query-support"))
                    answer = response.json()
                    check(
                        "answerable query released",
                        response.status_code == 200 and answer["status"] == "answered",
                    )
                    sources = {
                        document["id"]: document["text"]
                        for document in fixture("documents")["documents"]
                    }
                    check(
                        "exact source offsets",
                        bool(answer["citations"])
                        and all(
                            sources[c["document_id"]][c["start"] : c["end"]] == c["quote"]
                            for c in answer["citations"]
                        ),
                    )
                    check(
                        "every claim has citation",
                        all(
                            any(c["claim_index"] == index for c in answer["citations"])
                            for index in range(len(answer["claims"]))
                        ),
                    )
                    check(
                        "trace propagation",
                        answer["trace_id"] == response.headers["x-trace-id"]
                        and answer["trace_id"] != "0" * 32,
                    )
                    check("unknown query abstains", query("query-unknown")["status"] == "abstained")

                    send("POST", "/ingest", json=fixture("restricted")).raise_for_status()
                    denied = query("query-hr", staff)
                    check(
                        "group ACL filters before retrieval",
                        "hr-private" not in [h["chunk"]["document_id"] for h in denied["contexts"]]
                        and "JADE retirement allocation is 450 units" not in json.dumps(denied),
                    )
                    allowed = query("query-hr", hr)
                    check(
                        "authorized HR identity retrieves fixture",
                        allowed["status"] == "answered" and "450" in allowed["answer"],
                    )
                    send("POST", "/ingest", other, json=fixture("other-tenant")).raise_for_status()
                    own = query("query-support", staff)
                    other_answer = query("query-support", other)
                    check(
                        "tenant isolation with same document ID",
                        "ORCHID" not in json.dumps(own) and "ORCHID" in other_answer["answer"],
                    )

                    review = query("query-review")
                    check(
                        "high-risk review withholds claims",
                        review["status"] == "review"
                        and not review["claims"]
                        and not review["citations"],
                    )
                    queue = send("GET", "/reviews").json()
                    check(
                        "review persisted",
                        review["request_id"] in [record["request_id"] for record in queue],
                    )
                    path = f"/reviews/{review['request_id']}/decision"
                    check(
                        "review decision accepted",
                        send("POST", path, json=fixture("review-decision")).status_code == 200,
                    )
                    check(
                        "duplicate review decision rejected",
                        send("POST", path, json=fixture("review-decision")).status_code == 404,
                    )

                    old_version = own["citations"][0]["version"]
                    send("POST", "/ingest", json=fixture("update-support")).raise_for_status()
                    updated = query("query-support", staff)
                    check(
                        "replacement source/version used",
                        updated["status"] == "answered"
                        and "8 hours" in updated["answer"]
                        and all(c["version"] != old_version for c in updated["citations"]),
                    )
                    check(
                        "delete removes tenant document",
                        send("DELETE", "/documents/support").json()["deleted_chunks"] == 1,
                    )
                    remaining = query("query-support", staff)
                    check(
                        "deleted source absent from retrieval",
                        all(h["chunk"]["document_id"] != "support" for h in remaining["contexts"]),
                    )
                    check(
                        "other tenant survives deletion",
                        query("query-support", other)["status"] == "answered",
                    )
            except Exception as exc:
                failure = f"{type(exc).__name__}: {exc}"
            finally:
                process.terminate()
                process.wait(timeout=10)
                if failure:
                    log.seek(0)
                    print(log.read()[-4000:], file=sys.stderr)
    report = {
        "mode": "demo",
        "scope": "Isolated real HTTP API; no paid model calls",
        "passed": failure is None,
        "check_count": len(records),
        "checks": records,
        "error": failure,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "checks"}, indent=2))
    raise SystemExit(0 if failure is None else 1)


if __name__ == "__main__":
    main()
