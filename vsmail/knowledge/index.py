"""The vector index: build it, persist it, search it.

A numpy matrix on disk rather than a vector database. 531 chunks is a 531x384
float32 array — 800 KB — and searching it is one dot product. A server would
add a dependency, a process to keep alive and a second thing that can be down
during a demo, in exchange for nothing at this size.

Built ahead of time by `scripts/build_index.py` and committed, so a deploy
starts without embedding the corpus. The encoder still loads at query time to
embed the question, which is one short forward pass.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np

from vsmail.knowledge.chunks import Chunk, load_all
from vsmail.knowledge.embed import DIMENSIONS, encode

#: Where the built index lives.
INDEX = Path(__file__).resolve().parent.parent.parent / "knowledge" / "index.npz"

#: Below this, the best match is not really about the question. Retrieving
#: something irrelevant is worse than retrieving nothing: it gives the model
#: material to be confidently wrong from.
#:
#: Measured rather than picked. Across the five question types the inbox
#: actually contains, the right chunk scores 0.74-0.86; an out-of-scope
#: question ("what is the office holiday schedule?") tops out at 0.54. 0.60
#: separates them with room on both sides.
MIN_SCORE = 0.60

#: The identifiers the emails quote. A reference number is an exact key, not
#: something to match semantically — every booking reference looks alike to an
#: embedding, so asking about 5AAT-94519 happily retrieved 5SUS-22342 at 0.74.
#: These are looked up, never searched.
IDENTIFIERS = (
    re.compile(r"\b(52\d{8})\b"),          # invoice
    re.compile(r"\b(\d[A-Z]{3}-\d{5})\b"),  # booking
)


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float

    def as_dict(self) -> dict:
        return {**self.chunk.as_dict(), "score": round(self.score, 4)}


def build(path: Path | None = None) -> int:
    """Embed the whole corpus and write the index. Returns the chunk count."""
    path = path or INDEX
    chunks = load_all()
    if not chunks:
        raise RuntimeError("no chunks found; is knowledge/ populated?")

    vectors = encode([c.text for c in chunks])
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        vectors=vectors,
        meta=np.array(json.dumps([c.as_dict() for c in chunks]), dtype=object),
    )
    return len(chunks)


class Index:
    """A built index, loaded once and searched many times."""

    def __init__(self, path: Path | None = None):
        self.path = path or INDEX
        data = np.load(self.path, allow_pickle=True)
        self.vectors: np.ndarray = data["vectors"]
        self.chunks = [Chunk(**c) for c in json.loads(str(data["meta"]))]
        if self.vectors.shape != (len(self.chunks), DIMENSIONS):
            raise RuntimeError(
                f"index at {self.path} is {self.vectors.shape}, expected "
                f"{(len(self.chunks), DIMENSIONS)} — rebuild it"
            )

    def records_named_in(self, question: str) -> list[Hit]:
        """Records the question quotes by number, looked up exactly.

        Scored 1.0 because they are not a guess: the question asked about
        invoice 5250075931 and this *is* invoice 5250075931.
        """
        wanted: list[str] = []
        for pattern in IDENTIFIERS:
            wanted.extend(pattern.findall(question))
        if not wanted:
            return []
        by_id = {c.id: c for c in self.chunks}
        hits = []
        for ref in dict.fromkeys(wanted):
            for key in (f"invoice:{ref}", f"booking:{ref}"):
                if key in by_id:
                    hits.append(Hit(by_id[key], 1.0))
        return hits

    def search(self, question: str, k: int = 4, min_score: float = MIN_SCORE) -> list[Hit]:
        """What should be put in front of the model for this question.

        Two sources, deliberately separate. The records the question *names*
        are looked up by number. The explanation of what those numbers mean is
        retrieved by similarity over the policy documents only — records are
        never reached that way, because one booking reference embeds almost
        identically to another and a confidently retrieved wrong record is the
        worst thing this could hand the model.

        Returns fewer than `k` — possibly none — when nothing scores well
        enough. An empty result is the honest answer to a question the corpus
        does not cover, and the caller turns it into a refusal.
        """
        from vsmail.knowledge.embed import encode_query

        exact = self.records_named_in(question)

        policy = [i for i, c in enumerate(self.chunks) if not c.fabricated]
        scores = self.vectors[policy] @ encode_query(question)
        order = np.argsort(-scores)[:k]
        retrieved = [
            Hit(self.chunks[policy[i]], float(scores[i]))
            for i in order
            if scores[i] >= min_score
        ]
        return exact + retrieved


def available(path: Path | None = None) -> bool:
    return (path or INDEX).is_file()


@lru_cache(maxsize=1)
def get_index() -> "Index | None":
    """The index, loaded once. None when it has not been built.

    Cached because a request should not re-read and re-parse 765 KB, and
    because the answer path is already waiting on a model call.
    """
    if not available():
        return None
    return Index()
