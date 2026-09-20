"""Turning text into vectors, locally.

`bge-small-en-v1.5` as a quantized ONNX graph, run through onnxruntime. No
API and no key: DeepSeek offers no embeddings endpoint, and adding a second
vendor for this would break the one-key story the whole service is built on.
34 MB of weights committed to the repo, so a deploy needs nothing from
HuggingFace at build or boot.

Three details that are easy to get wrong and silent when you do — each cost
quality rather than raising an error:

1. **bge pools the CLS token**, not the mean of the sequence. Mean pooling
   runs fine and retrieves noticeably worse.
2. **Queries take a prefix**; passages do not. bge was trained asymmetrically
   and skipping it costs real accuracy.
3. **This export wants `token_type_ids`**, which most MiniLM examples omit.

Loading is lazy and cached — importing `vsmail` should not read 34 MB off
disk, and a test that never embeds anything should not pay for it.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import numpy as np

#: The model, overridable so a better one can be dropped in without code.
MODEL_DIR = Path(
    os.environ.get(
        "VS_EMBED_MODEL",
        str(Path(__file__).resolve().parent.parent.parent / "models" / "bge-small-en-v1.5"),
    )
)

#: What bge-small produces.
DIMENSIONS = 384

#: Prepended to a question, never to a passage. See the docstring.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

MAX_TOKENS = 512


class EmbedderUnavailable(RuntimeError):
    """No usable model. The caller degrades rather than crashing."""


@lru_cache(maxsize=1)
def _session():
    try:
        import onnxruntime as ort
        from tokenizers import Tokenizer
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise EmbedderUnavailable(
            "onnxruntime and tokenizers are needed to embed text; "
            "pip install -r requirements.txt"
        ) from exc

    model = MODEL_DIR / "model_quantized.onnx"
    vocab = MODEL_DIR / "tokenizer.json"
    if not model.is_file() or not vocab.is_file():
        raise EmbedderUnavailable(
            f"no embedding model at {MODEL_DIR}. Expected model_quantized.onnx "
            "and tokenizer.json."
        )

    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    tokenizer = Tokenizer.from_file(str(vocab))
    tokenizer.enable_padding()
    tokenizer.enable_truncation(max_length=MAX_TOKENS)
    inputs = {i.name for i in session.get_inputs()}
    return session, tokenizer, inputs


def available() -> bool:
    """Whether embedding is possible at all, without raising."""
    try:
        _session()
    except EmbedderUnavailable:
        return False
    return True


def encode(texts: list[str]) -> np.ndarray:
    """Embed passages. Returns L2-normalised rows, so a dot product is cosine."""
    if not texts:
        return np.zeros((0, DIMENSIONS), dtype=np.float32)

    session, tokenizer, names = _session()
    encoded = tokenizer.encode_batch(texts)
    feed = {
        "input_ids": np.array([e.ids for e in encoded], dtype=np.int64),
        "attention_mask": np.array([e.attention_mask for e in encoded], dtype=np.int64),
    }
    if "token_type_ids" in names:
        feed["token_type_ids"] = np.zeros_like(feed["input_ids"])

    hidden = session.run(None, feed)[0]
    vectors = hidden[:, 0]  # CLS, not mean.
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return (vectors / np.maximum(norms, 1e-12)).astype(np.float32)


def encode_query(question: str) -> np.ndarray:
    """Embed one question, with the prefix bge expects on the query side."""
    return encode([QUERY_PREFIX + question])[0]
