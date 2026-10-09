from __future__ import annotations

import time
from dataclasses import dataclass

from app.feature_store import OnlineFeatureStore
from app.models import ModelRegistry


@dataclass(frozen=True)
class ShadowResult:
    model_version: str
    risk_score: float
    absolute_delta: float


@dataclass(frozen=True)
class ScoreResult:
    model_version: str
    risk_score: float
    feature_age_ms: float
    inference_latency_ms: float
    shadow: ShadowResult


class ServingService:
    def __init__(self, store: OnlineFeatureStore, registry: ModelRegistry) -> None:
        self.store = store
        self.registry = registry

    async def score(self, customer_id: str, request_id: str) -> ScoreResult:
        started = time.perf_counter()
        features, age_ms = await self.store.get(customer_id)
        selected, shadow_model = self.registry.select(request_id)
        score = selected.predict(features)
        shadow_score = shadow_model.predict(features)
        return ScoreResult(
            model_version=selected.version,
            risk_score=score,
            feature_age_ms=age_ms,
            inference_latency_ms=(time.perf_counter() - started) * 1000,
            shadow=ShadowResult(shadow_model.version, shadow_score, abs(score - shadow_score)),
        )
