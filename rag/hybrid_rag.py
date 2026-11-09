import hashlib
import math
import re
from collections import Counter

from rank_bm25 import BM25Okapi


def tokens(text):
    return re.findall(r"[a-z0-9]+(?:-[a-z0-9]+)*", text.lower())


def vector(text):
    values = [0.0] * 128
    for token, count in Counter(tokens(text)).items():
        index = int(hashlib.sha256(token.encode()).hexdigest()[:8], 16) % len(values)
        values[index] += count
    norm = math.sqrt(sum(x * x for x in values)) or 1
    return [x / norm for x in values]


def cosine(left, right):
    return sum(a * b for a, b in zip(left, right, strict=True))


class HybridRAG:
    def __init__(self, ingestion, reranker=None, semantic_backend=None):
        self.ingestion = ingestion
        self.reranker = reranker
        self.semantic_backend = semantic_backend

    def retrieve(self, scope, query, part_id, k=6):
        if not 1 <= k <= 20:
            raise ValueError("Retrieval budget must be between 1 and 20")
        candidates = []
        for document in self.ingestion.current(scope):
            if document["metadata"]["part_id"] != part_id:
                continue
            for chunk in document["chunks"]:
                candidates.append({**chunk, "metadata": document["metadata"]})
        if not candidates:
            return []
        bm25 = BM25Okapi([tokens(row["text"]) for row in candidates])
        keyword = list(bm25.get_scores(tokens(query)))
        if self.semantic_backend:
            embeddings = self.semantic_backend.encode([query, *[row["text"] for row in candidates]])
            dense = [cosine(embeddings[0], embedding) for embedding in embeddings[1:]]
        else:
            query_vector = vector(query)
            dense = [cosine(query_vector, row["embedding"]) for row in candidates]
        scores = [0.0] * len(candidates)
        for values in (keyword, dense):
            for rank, index in enumerate(
                sorted(range(len(values)), key=lambda i: (-values[i], candidates[i]["chunk_id"]))
            ):
                scores[index] += 1 / (60 + rank + 1)
        for i, row in enumerate(candidates):
            row["score"] = round(scores[i], 8)
        ranked = sorted(candidates, key=lambda row: (-row["score"], row["chunk_id"]))
        if self.reranker:
            ranked = self.reranker(query, ranked[:20])
        elif self.semantic_backend:
            ranked = self.semantic_backend.rerank(query, ranked[:20])
        return [
            {key: value for key, value in row.items() if key != "embedding"} for row in ranked[:k]
        ]


class CrossEncoderReranker:
    def __init__(self, model):
        self.model = model

    def __call__(self, query, candidates):
        scores = self.model.predict([(query, row["text"]) for row in candidates])
        return sorted(
            [
                {**row, "rerank_score": float(score)}
                for row, score in zip(candidates, scores, strict=True)
            ],
            key=lambda row: -row["rerank_score"],
        )
