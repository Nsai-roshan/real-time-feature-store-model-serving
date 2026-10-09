from __future__ import annotations

import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException, Response
from prometheus_client import Counter, Histogram, make_asgi_app
from pydantic import BaseModel, Field

from app.feature_store import FEATURE_NAMES, OnlineFeatureStore
from app.models import ModelRegistry, RiskModel
from app.service import ServingService
from app.shadow import SHADOW_SUMMARY_KEY, ShadowRecorder
from app.timing import ServerTimingMiddleware

REQUESTS = Counter(
    "model_score_requests_total", "Model score requests", ["status", "model_version"]
)
LATENCY = Histogram(
    "model_score_latency_seconds",
    "End-to-end score latency",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1),
)
SHADOW_DELTA = Histogram(
    "model_shadow_absolute_delta",
    "Absolute primary/candidate prediction delta",
    buckets=(0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 1),
)


class FeaturePayload(BaseModel):
    transaction_count_1h: float = Field(ge=0)
    amount_sum_24h: float = Field(ge=0)
    account_age_days: float = Field(ge=0)
    country_risk_score: float = Field(ge=0, le=1)


class ScoreRequest(BaseModel):
    customer_id: str = Field(min_length=1, max_length=128)
    request_id: str | None = Field(default=None, max_length=128)


def default_registry() -> ModelRegistry:
    primary = RiskModel(
        "primary-v1",
        -3.0,
        {
            "transaction_count_1h": 0.20,
            "amount_sum_24h": 0.002,
            "account_age_days": -0.002,
            "country_risk_score": 1.20,
        },
    )
    candidate = RiskModel(
        "candidate-v2",
        -2.9,
        {
            "transaction_count_1h": 0.22,
            "amount_sum_24h": 0.002,
            "account_age_days": -0.002,
            "country_risk_score": 1.15,
        },
    )
    return ModelRegistry(primary, candidate, int(os.getenv("CANDIDATE_TRAFFIC_PERCENT", "10")))


def create_app(redis_client=None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.redis = redis_client or redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True
        )
        app.state.service = ServingService(
            OnlineFeatureStore(app.state.redis, int(os.getenv("FEATURE_TTL_SECONDS", "900"))),
            default_registry(),
        )
        app.state.shadow_recorder = ShadowRecorder(app.state.redis)
        stop = asyncio.Event()
        recorder_task = asyncio.create_task(app.state.shadow_recorder.run(stop))
        yield
        stop.set()
        await recorder_task
        if redis_client is None:
            await app.state.redis.aclose()

    app = FastAPI(title="Real-Time Feature Serving", version="0.1.0", lifespan=lifespan)
    app.add_middleware(ServerTimingMiddleware, histogram=LATENCY)
    if redis_client is not None:
        app.state.redis = redis_client
        app.state.service = ServingService(
            OnlineFeatureStore(redis_client, int(os.getenv("FEATURE_TTL_SECONDS", "900"))),
            default_registry(),
        )
        app.state.shadow_recorder = ShadowRecorder(redis_client)
    app.mount("/metrics", make_asgi_app())

    @app.get("/healthz")
    async def healthz():
        try:
            await app.state.redis.ping()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="redis unavailable") from exc
        return {"status": "ok"}

    @app.put("/v1/features/{customer_id}", status_code=204)
    async def upsert_features(customer_id: str, payload: FeaturePayload):
        await app.state.service.store.put(customer_id, payload.model_dump())
        return Response(status_code=204)

    @app.post("/v1/score")
    async def score(payload: ScoreRequest):
        try:
            result = await app.state.service.score(
                payload.customer_id, payload.request_id or str(uuid.uuid4())
            )
        except KeyError as exc:
            REQUESTS.labels(status="not_found", model_version="none").inc()
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            REQUESTS.labels(status="invalid_features", model_version="none").inc()
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        REQUESTS.labels(status="ok", model_version=result.model_version).inc()
        SHADOW_DELTA.observe(result.shadow.absolute_delta)
        app.state.shadow_recorder.record(result.shadow.absolute_delta)
        return {
            "customer_id": payload.customer_id,
            "model_version": result.model_version,
            "risk_score": round(result.risk_score, 6),
            "feature_age_ms": round(result.feature_age_ms, 3),
            "inference_latency_ms": round(result.inference_latency_ms, 3),
            "shadow": {
                "model_version": result.shadow.model_version,
                "risk_score": round(result.shadow.risk_score, 6),
                "absolute_delta": round(result.shadow.absolute_delta, 6),
            },
        }

    @app.get("/v1/models/candidate/promotion-check")
    async def promotion_check():
        await app.state.shadow_recorder.flush()
        summary = await app.state.redis.hgetall(SHADOW_SUMMARY_KEY)
        sample_count = int(summary.get("sample_count", 0))
        mean_delta = (
            float(summary.get("absolute_delta_sum", 0)) / sample_count if sample_count else 0.0
        )
        decision = app.state.service.registry.evaluate_promotion(
            sample_count=sample_count,
            mean_absolute_delta=mean_delta,
            max_allowed_delta=float(os.getenv("MAX_SHADOW_MEAN_ABSOLUTE_DELTA", "0.03")),
            minimum_samples=int(os.getenv("MINIMUM_SHADOW_SAMPLES", "500")),
        )
        return {
            "candidate_version": app.state.service.registry.candidate.version,
            "sample_count": sample_count,
            "mean_absolute_delta": round(mean_delta, 6),
            "promote": decision.promote,
            "reason": decision.reason,
        }

    @app.get("/v1/feature-contract")
    async def feature_contract():
        return {
            "entity": "customer_id",
            "features": FEATURE_NAMES,
            "ttl_seconds": app.state.service.store.feature_ttl_seconds,
        }

    return app


app = create_app()
