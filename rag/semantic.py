class SemanticBackend:
    def __init__(self, embedding_path, reranker_path, embedding_model=None, reranker_model=None):
        if embedding_model is None or reranker_model is None:
            if not embedding_path or not reranker_path:
                raise ValueError("Set local EMBEDDING_MODEL_PATH and RERANKER_MODEL_PATH")
            import torch
            from sentence_transformers import CrossEncoder, SentenceTransformer

            torch.set_num_threads(2)

            embedding_model = SentenceTransformer(
                embedding_path, device="cpu", local_files_only=True, trust_remote_code=False
            )
            reranker_model = CrossEncoder(
                reranker_path, device="cpu", local_files_only=True, trust_remote_code=False
            )
        self.embedder = embedding_model
        self.reranker = reranker_model
        self.minimum_memory_score = -5.0
        self.identity = f"{embedding_path}|{reranker_path}"

    def encode(self, texts):
        return self.embedder.encode(texts, normalize_embeddings=True).tolist()

    def rerank(self, query, rows):
        scores = self.reranker.predict([(query, row["text"]) for row in rows])
        return sorted(
            [
                {**row, "rerank_score": float(score)}
                for row, score in zip(rows, scores, strict=True)
            ],
            key=lambda row: -row["rerank_score"],
        )
