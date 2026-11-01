"""Qdrant-backed local vector collections with a cloud endpoint switch."""

from __future__ import annotations

import os
import uuid
from typing import Any

COLLECTIONS = ("cascade_cases", "theft_cases", "documents")


class QdrantCaseStore:
    """Thin adapter for three named collections; embeddings stay producer-owned."""

    def __init__(self, url: str | None = None, api_key: str | None = None,
                 vector_size: int | None = None):
        try:
            from qdrant_client import QdrantClient, models
        except ImportError as exc:
            raise RuntimeError("Install qdrant-client to use the vector store") from exc
        self._models = models
        self.vector_size = vector_size or int(os.getenv("QDRANT_VECTOR_SIZE", "128"))
        self.client = QdrantClient(
            url=url or os.getenv("QDRANT_URL", "http://localhost:6333"),
            api_key=api_key or os.getenv("QDRANT_API_KEY") or None,
        )

    def ensure_collections(self) -> list[str]:
        existing = {item.name for item in self.client.get_collections().collections}
        created = []
        for name in COLLECTIONS:
            if name not in existing:
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=self._models.VectorParams(
                        size=self.vector_size,
                        distance=self._models.Distance.COSINE,
                    ),
                )
                created.append(name)
        return created

    def upsert(self, collection: str, ids: list[str], vectors: list[list[float]],
               payloads: list[dict[str, Any]] | None = None) -> None:
        self._check_collection(collection)
        if len(ids) != len(vectors):
            raise ValueError("ids and vectors must have equal lengths")
        payloads = payloads or [{} for _ in ids]
        if len(payloads) != len(ids):
            raise ValueError("payloads and ids must have equal lengths")
        points = []
        for external_id, vector, payload in zip(ids, vectors, payloads):
            if len(vector) != self.vector_size:
                raise ValueError(f"expected vectors of length {self.vector_size}")
            point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"cascadeguard:{collection}:{external_id}"))
            points.append(self._models.PointStruct(
                id=point_id, vector=vector,
                payload={**payload, "external_id": external_id},
            ))
        if points:
            self.client.upsert(collection_name=collection, points=points, wait=True)

    def search(self, collection: str, vector: list[float], limit: int = 5,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        self._check_collection(collection)
        if len(vector) != self.vector_size:
            raise ValueError(f"expected vector of length {self.vector_size}")
        query_filter = None
        if filters:
            conditions = [self._models.FieldCondition(
                key=key, match=self._models.MatchValue(value=value))
                for key, value in filters.items()]
            query_filter = self._models.Filter(must=conditions)
        response = self.client.query_points(
            collection_name=collection, query=vector, query_filter=query_filter,
            limit=limit, with_payload=True,
        )
        hits = []
        for point in response.points:
            payload = point.payload or {}
            hits.append({"id": payload.get("external_id", str(point.id)),
                         "score": float(point.score), "payload": payload})
        return hits

    @staticmethod
    def _check_collection(name: str) -> None:
        if name not in COLLECTIONS:
            raise ValueError(f"collection must be one of {COLLECTIONS}")


if __name__ == "__main__":
    store = QdrantCaseStore()
    created = store.ensure_collections()
    print(f"Qdrant collections ready: {', '.join(COLLECTIONS)}")
    print(f"Created: {', '.join(created) if created else 'none (already existed)'}")
