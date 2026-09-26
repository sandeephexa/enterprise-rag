"""Exercise real local neural backends; no generator API call or API key needed."""

import argparse
import json
import time

from rag.config import Settings
from rag.guardrails import NeuralEntailment
from rag.ingestion import SemanticEncoder
from rag.retriever import CrossEncoderRanker

parser = argparse.ArgumentParser()
parser.add_argument("--output", default="neural-smoke.json")
args = parser.parse_args()
settings = Settings(mode="demo")
started = time.monotonic()
encoder = SemanticEncoder(settings)
vectors = encoder.encode(
    [
        "How can I reset my password?",
        "Reset your password in account settings.",
        "Bananas grow in tropical climates.",
    ]
)
ranker = CrossEncoderRanker(settings)
rank_scores = ranker.score(
    [
        ("How can I reset my password?", "Reset your password in account settings."),
        ("How can I reset my password?", "Bananas grow in tropical climates."),
    ]
)
nli = NeuralEntailment(settings)
nli_scores = nli.scores(
    [
        ("Support is available 24 hours a day.", "Support is available 24 hours a day."),
        ("Support is never available on Sundays.", "Support is available on Sundays."),
    ]
)
passed = bool(
    vectors[0] @ vectors[1] > vectors[0] @ vectors[2]
    and rank_scores[0] > rank_scores[1]
    and nli_scores[0][0] > 0.85
    and nli_scores[1][1] > 0.2
)
report = {
    "passed": passed,
    "embedding_shape": list(vectors.shape),
    "embedding_cosines": [float(vectors[0] @ vectors[1]), float(vectors[0] @ vectors[2])],
    "rerank_scores": rank_scores,
    "nli_entailment_contradiction": nli_scores,
    "load_and_run_seconds": time.monotonic() - started,
    "revisions": {
        "embedding": encoder.model[0].auto_model.config._commit_hash,
        "reranker": ranker.model.model.config._commit_hash,
        "nli": nli.model.model.config._commit_hash,
    },
    "scope": "Neural smoke only; not a quality benchmark or live generator test",
}
with open(args.output, "w") as stream:
    json.dump(report, stream, indent=2, allow_nan=False)
print(json.dumps(report, indent=2))
raise SystemExit(0 if passed else 1)
