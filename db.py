from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class DbStatus:
    enabled: bool
    ok: bool
    message: str


class PredictionStore:
    def __init__(self, mongodb_uri: str | None, db_name: str, collection_name: str):
        self._enabled = bool(mongodb_uri)
        self._mongodb_uri = mongodb_uri
        self._db_name = db_name
        self._collection_name = collection_name

        self._client = None
        self._collection = None

    @property
    def enabled(self) -> bool:
        return self._enabled

    def connect(self) -> None:
        if not self._enabled:
            return

        if self._collection is not None:
            return

        from pymongo import MongoClient  # lazy import

        self._client = MongoClient(self._mongodb_uri, serverSelectionTimeoutMS=2000)
        db = self._client[self._db_name]
        self._collection = db[self._collection_name]

        # Touch the server to surface connection errors early
        self._client.admin.command("ping")

    def status(self) -> DbStatus:
        if not self._enabled:
            return DbStatus(enabled=False, ok=True, message="MongoDB disabled (MONGODB_URI not set)")

        try:
            self.connect()
            return DbStatus(enabled=True, ok=True, message="MongoDB connected")
        except Exception as e:  # pylint: disable=broad-except
            return DbStatus(enabled=True, ok=False, message=f"MongoDB error: {e}")

    def insert_prediction(self, doc: dict[str, Any]) -> str | None:
        if not self._enabled:
            return None

        self.connect()
        assert self._collection is not None

        doc = dict(doc)
        doc.setdefault("createdAt", datetime.now(timezone.utc))

        result = self._collection.insert_one(doc)
        return str(result.inserted_id)

    def list_predictions(self, limit: int = 50) -> list[dict[str, Any]]:
        if not self._enabled:
            return []

        self.connect()
        assert self._collection is not None

        cursor = self._collection.find({}, sort=[("createdAt", -1)], limit=max(1, min(limit, 200)))
        items: list[dict[str, Any]] = []
        for item in cursor:
            # ObjectId and datetime are not JSON serializable by default
            item["_id"] = str(item.get("_id"))
            created_at = item.get("createdAt")
            if isinstance(created_at, datetime):
                item["createdAt"] = created_at.astimezone(timezone.utc).isoformat()
            items.append(item)
        return items
