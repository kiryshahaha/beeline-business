"""Markdown knowledge base split into `##` sections and searched with BM25.

The base is small and curated, so lexical search with Russian stemming is enough
and needs no embedding model next to the chat model.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import snowballstemmer
import yaml

_WORD = re.compile(r"[а-яa-z0-9]+")
_STEMMER = snowballstemmer.stemmer("russian")
_STOPWORDS = frozenset(
    "а без бы в во вот все всё вы да для до его ее её если есть же за и из или им их к как"
    " ли мне мой моя мою на над не нет ни но о об он она они от по под при с со так там то"
    " у уже чем что чтобы это эта этот этой я ваш вам вас меня мы нас нам свой свою себя"
    " можно нужно надо какой какая какие каких кто где когда почему зачем сколько".split()
)
_BM25_K1 = 1.5
_BM25_B = 0.75
_WORK_TYPE_BOOST = 0.5
_OTHER_WORK_TYPE_PENALTY = 0.5


def tokenize(text: str) -> list[str]:
    words = _WORD.findall(text.lower().replace("ё", "е"))
    return _STEMMER.stemWords([word for word in words if word not in _STOPWORDS])


@dataclass(frozen=True)
class Chunk:
    path: str
    title: str
    section: str
    text: str
    roles: frozenset[str]
    work_type: str | None
    tokens: tuple[str, ...] = field(repr=False, compare=False)


def _split_front_matter(raw: str, path: Path) -> tuple[dict, str]:
    if not raw.startswith("---\n"):
        raise ValueError(f"{path}: нет front matter")
    header, _, body = raw[4:].partition("\n---\n")
    return yaml.safe_load(header), body


def load_chunks(root: Path) -> list[Chunk]:
    chunks = []
    for path in sorted(root.rglob("*.md")):
        if path.name == "README.md":
            continue
        meta, body = _split_front_matter(path.read_text(encoding="utf-8"), path)
        title = meta["title"]
        for block in re.split(r"^## ", body, flags=re.MULTILINE)[1:]:
            section, _, text = block.partition("\n")
            text = text.strip()
            chunks.append(
                Chunk(
                    path=str(path.relative_to(root)),
                    title=title,
                    section=section.strip(),
                    text=text,
                    roles=frozenset(meta["roles"]),
                    work_type=meta.get("work_type"),
                    # The title is repeated so that a query naming the topic finds every section.
                    tokens=tuple(tokenize(f"{title} {title} {section} {text}")),
                )
            )
    return chunks


class KnowledgeBase:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        self._term_counts = [Counter(chunk.tokens) for chunk in chunks]
        self._avg_length = sum(len(chunk.tokens) for chunk in chunks) / max(len(chunks), 1)
        document_frequency = Counter(term for counts in self._term_counts for term in counts)
        total = len(chunks)
        self._idf = {
            term: math.log(1 + (total - freq + 0.5) / (freq + 0.5))
            for term, freq in document_frequency.items()
        }

    @classmethod
    def from_dir(cls, root: Path) -> "KnowledgeBase":
        return cls(load_chunks(root))

    def _bm25(self, index: int, query: list[str]) -> float:
        counts = self._term_counts[index]
        length_norm = 1 - _BM25_B + _BM25_B * len(self.chunks[index].tokens) / self._avg_length
        score = 0.0
        for term in query:
            freq = counts.get(term, 0)
            if freq:
                score += self._idf[term] * freq * (_BM25_K1 + 1) / (freq + _BM25_K1 * length_norm)
        return score

    def search(self, query: str, role: str, k: int, work_type: str | None = None) -> list[Chunk]:
        """Top-k sections visible to the role; sections of the open ticket's work type rank up."""
        terms = tokenize(query)
        scored = [
            (self._bm25(index, terms), index)
            for index, chunk in enumerate(self.chunks)
            if role in chunk.roles
        ]
        best = max((score for score, _ in scored), default=0.0) or 1.0
        if work_type:
            # Tips for other work types mislead a small model about the open ticket.
            scored = [
                (score + _WORK_TYPE_BOOST * best, index)
                if self.chunks[index].work_type == work_type
                else (score * _OTHER_WORK_TYPE_PENALTY, index)
                if self.chunks[index].work_type
                else (score, index)
                for score, index in scored
            ]
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [self.chunks[index] for score, index in scored[:k] if score > 0]
