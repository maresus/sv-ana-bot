"""
RAG search for Sv. Ana bot.
Uses BM25 + topic boosting for better coverage of synonym queries.
"""
from __future__ import annotations

import json
import math
import re
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class Chunk:
    title: str
    paragraph: str
    url: str | None = None
    topic: str = ""


# Global storage
_CHUNKS: list[Chunk] = []
_BM25_INDEX: dict[str, list[tuple[int, float]]] = {}
_DOC_LENGTHS: list[int] = []
_AVG_DOC_LEN: float = 0.0

# Topic boosting: query keywords → topic to boost
TOPIC_BOOSTS: list[tuple[list[str], str, float]] = [
    (["zdravnik", "zdravnici", "zdravstvo", "ambulanta", "zdravstveni", "ordinacija", "splošni", "osebni"], "health", 3.0),
    (["svetnik", "svetniki", "občinski svet", "svet", "obcinski"], "council", 3.0),
    (["župan", "zupan", "županja", "županova"], "mayor", 3.0),
    (["podžupan", "podzupan", "podžupanja"], "mayor", 3.0),
    (["društvo", "drustvo", "klub", "konjeniki", "gasilci", "vinogradniki", "čebelarji"], "society", 3.0),
    (["turizem", "turistično", "znamenitost", "pohod", "pot", "izlet"], "tourism", 2.0),
    (["vloga", "obrazec", "postopek", "prošnja", "vloge", "obrazci"], "forms", 3.0),
    (["razpis", "razpisati", "sofinanciranje", "javni razpis"], "tender", 3.0),
    (["novica", "novosti", "aktualno", "obvestilo"], "news", 2.0),
    (["šola", "vrtec", "osnovna", "izobraževanje", "učenci"], "education", 3.0),
    (["kontakt", "telefon", "email", "naslov", "uradne ure"], "contact", 3.0),
    (["vas", "kraj", "naselje", "lokavec", "kremberk", "dražen", "žice"], "settlement", 2.0),
    (["nagrada", "priznanje", "dobitnik"], "awards", 3.0),
]


def _tokenize(text: str) -> list[str]:
    return [t for t in re.split(r'[^a-zA-ZčšžćđČŠŽĆĐ0-9]+', text.lower()) if len(t) >= 2]


def load_knowledge(path: str | Path) -> int:
    global _CHUNKS, _BM25_INDEX, _DOC_LENGTHS, _AVG_DOC_LEN

    path = Path(path)
    if not path.exists():
        return 0

    _CHUNKS = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                _CHUNKS.append(Chunk(
                    title=obj.get('title', ''),
                    paragraph=obj.get('content', '') or obj.get('paragraph', ''),
                    url=obj.get('url'),
                    topic=obj.get('topic', ''),
                ))
            except json.JSONDecodeError:
                continue

    _BM25_INDEX = {}
    _DOC_LENGTHS = []

    for idx, chunk in enumerate(_CHUNKS):
        text = f"{chunk.title} {chunk.paragraph}"
        tokens = _tokenize(text)
        _DOC_LENGTHS.append(len(tokens))

        tf_map: dict[str, int] = {}
        for token in tokens:
            tf_map[token] = tf_map.get(token, 0) + 1

        for term, count in tf_map.items():
            if term not in _BM25_INDEX:
                _BM25_INDEX[term] = []
            _BM25_INDEX[term].append((idx, count))

    _AVG_DOC_LEN = sum(_DOC_LENGTHS) / len(_DOC_LENGTHS) if _DOC_LENGTHS else 1.0

    return len(_CHUNKS)


def _get_topic_boosts(query: str) -> dict[str, float]:
    """Return topic -> boost_factor based on query keywords."""
    q = query.lower()
    boosts: dict[str, float] = {}
    for keywords, topic, factor in TOPIC_BOOSTS:
        if any(kw in q for kw in keywords):
            boosts[topic] = max(boosts.get(topic, 1.0), factor)
    return boosts


def search(query: str, top_k: int = 4) -> list[Chunk]:
    if not _CHUNKS:
        return []

    query_tokens = _tokenize(query)
    topic_boosts = _get_topic_boosts(query)

    k1 = 1.5
    b = 0.75
    n_docs = len(_CHUNKS)

    scores: dict[int, float] = {}

    for token in query_tokens:
        if token not in _BM25_INDEX:
            continue

        postings = _BM25_INDEX[token]
        df = len(postings)
        idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1)

        for doc_idx, tf in postings:
            doc_len = _DOC_LENGTHS[doc_idx]
            tf_norm = (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * doc_len / _AVG_DOC_LEN))
            scores[doc_idx] = scores.get(doc_idx, 0) + idf * tf_norm

    # Apply topic boosts
    if topic_boosts:
        for doc_idx, chunk in enumerate(_CHUNKS):
            boost = topic_boosts.get(chunk.topic, 1.0)
            if boost > 1.0:
                # Boost even docs with 0 BM25 score so topic-relevant docs surface
                scores[doc_idx] = scores.get(doc_idx, 0.01) * boost

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [_CHUNKS[idx] for idx, _ in ranked[:top_k]]


def get_context(query: str, top_k: int = 4) -> str:
    chunks = search(query, top_k)
    if not chunks:
        return ""

    parts = []
    for chunk in chunks:
        text = chunk.paragraph.strip()
        if chunk.title:
            text = f"[{chunk.title}] {text}"
        parts.append(text)

    return "\n\n".join(parts)
