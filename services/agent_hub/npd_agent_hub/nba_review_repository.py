from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from typing import Protocol

from .nba_review_models import NBAReviewRecord
from .store import HubStore, MemoryHubStore, RedisHubStore


NBA_REVIEW_RETENTION = 5000


class NBAReviewRepository(Protocol):
    def save(self, review: NBAReviewRecord) -> None: ...

    def list(
        self,
        *,
        subject_ref: str | None = None,
        limit: int = 100,
    ) -> list[NBAReviewRecord]: ...


@dataclass
class MemoryNBAReviewRepository:
    reviews: dict[str, NBAReviewRecord] = field(default_factory=dict)

    def save(self, review: NBAReviewRecord) -> None:
        existing = self.reviews.get(review.review_id)
        if existing is not None and existing != review:
            raise ValueError("NBA review record is immutable")
        self.reviews[review.review_id] = review.model_copy(deep=True)
        overflow = len(self.reviews) - NBA_REVIEW_RETENTION
        if overflow > 0:
            expired = sorted(
                self.reviews.values(),
                key=lambda item: (item.reviewed_at, item.review_id),
            )[:overflow]
            for item in expired:
                self.reviews.pop(item.review_id, None)

    def list(
        self,
        *,
        subject_ref: str | None = None,
        limit: int = 100,
    ) -> list[NBAReviewRecord]:
        limit = max(1, min(limit, 1000))
        rows = sorted(
            self.reviews.values(),
            key=lambda item: (item.reviewed_at, item.review_id),
            reverse=True,
        )
        if subject_ref is not None:
            rows = [item for item in rows if item.subject_ref == subject_ref]
        return [item.model_copy(deep=True) for item in rows[:limit]]


class RedisNBAReviewRepository:
    def __init__(self, store: RedisHubStore):
        self.store = store
        self.redis = store.redis

    def _key(self, *parts: str) -> str:
        return self.store._key("phase9-os", "nba-review", *parts)

    @staticmethod
    def _subject_hash(subject_ref: str) -> str:
        return sha256(subject_ref.encode("utf-8")).hexdigest()[:24]

    def _review_key(self, review_id: str) -> str:
        return self._key("record", review_id)

    def _global_index(self) -> str:
        return self._key("reviews")

    def _subject_index(self, subject_ref: str) -> str:
        return self._key("subject", self._subject_hash(subject_ref), "reviews")

    def save(self, review: NBAReviewRecord) -> None:
        key = self._review_key(review.review_id)
        if not self.redis.set(key, review.model_dump_json(), nx=True):
            existing = self.redis.get(key)
            if existing and NBAReviewRecord.model_validate_json(existing) == review:
                return
            raise ValueError("NBA review record is immutable")

        score = review.reviewed_at.timestamp()
        pipe = self.redis.pipeline()
        pipe.zadd(self._global_index(), {review.review_id: score})
        pipe.zadd(self._subject_index(review.subject_ref), {review.review_id: score})
        pipe.execute()
        self._prune()

    def _load(self, review_id: str) -> NBAReviewRecord | None:
        raw = self.redis.get(self._review_key(review_id))
        return NBAReviewRecord.model_validate_json(raw) if raw else None

    def _prune(self) -> None:
        overflow = int(self.redis.zcard(self._global_index())) - NBA_REVIEW_RETENTION
        if overflow <= 0:
            return
        expired_ids = self.redis.zrange(self._global_index(), 0, overflow - 1)
        for review_id in expired_ids:
            review_id = str(review_id)
            review = self._load(review_id)
            pipe = self.redis.pipeline()
            pipe.zrem(self._global_index(), review_id)
            if review is not None:
                pipe.zrem(self._subject_index(review.subject_ref), review_id)
            pipe.delete(self._review_key(review_id))
            pipe.execute()

    def list(
        self,
        *,
        subject_ref: str | None = None,
        limit: int = 100,
    ) -> list[NBAReviewRecord]:
        limit = max(1, min(limit, 1000))
        index = (
            self._subject_index(subject_ref)
            if subject_ref is not None
            else self._global_index()
        )
        ids = self.redis.zrevrange(index, 0, limit - 1)
        rows = [self._load(str(review_id)) for review_id in ids]
        return [item for item in rows if item is not None]


def repository_for_store(store: HubStore) -> NBAReviewRepository:
    if isinstance(store, RedisHubStore):
        return RedisNBAReviewRepository(store)
    if isinstance(store, MemoryHubStore):
        existing = getattr(store, "_phase9_nba_review_repository", None)
        if existing is None:
            existing = MemoryNBAReviewRepository()
            setattr(store, "_phase9_nba_review_repository", existing)
        return existing
    raise TypeError(f"unsupported Agent Hub store backend for NBA reviews: {store.backend_name}")
