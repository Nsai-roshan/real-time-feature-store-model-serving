import time

import fakeredis.aioredis
import pytest
from httpx import ASGITransport, AsyncClient

from app.feature_store import OnlineFeatureStore
from app.models import ModelRegistry, RiskModel
from app.service import ServingService
from app.shadow import SHADOW_SUMMARY_KEY, ShadowRecorder


@pytest.fixture
async def service():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    store = OnlineFeatureStore(client, feature_ttl_seconds=300)
    now_ms = time.time() * 1000
    await client.hset(
        "customer:customer-1:features",
        mapping={
            "transaction_count_1h": "7",
            "amount_sum_24h": "250.0",
            "account_age_days": "120",
            "country_risk_score": "0.2",
            "updated_at_ms": str(now_ms),
        },
    )
    registry = ModelRegistry(
        primary=RiskModel(
            "primary-v1",
            intercept=-3.0,
            weights={
                "transaction_count_1h": 0.2,
                "amount_sum_24h": 0.002,
                "account_age_days": -0.002,
                "country_risk_score": 1.2,
            },
        ),
        candidate=RiskModel(
            "candidate-v2",
            intercept=-2.9,
            weights={
                "transaction_count_1h": 0.22,
                "amount_sum_24h": 0.002,
                "account_age_days": -0.002,
                "country_risk_score": 1.15,
            },
        ),
        candidate_traffic_percent=20,
    )
    return ServingService(store, registry)


async def test_scores_known_customer_and_runs_shadow(service):
    result = await service.score("customer-1", request_id="fixed-request")

    assert result.model_version in {"primary-v1", "candidate-v2"}
    assert 0 < result.risk_score < 1
    assert result.shadow.model_version in {"primary-v1", "candidate-v2"} - {result.model_version}
    assert result.feature_age_ms >= 0


async def test_returns_not_found_when_customer_has_no_online_features(service):
    with pytest.raises(KeyError, match="customer features not found"):
        await service.score("unknown", request_id="r-1")


async def test_ab_assignment_is_deterministic(service):
    first = await service.score("customer-1", request_id="same-request")
    second = await service.score("customer-1", request_id="same-request")

    assert first.model_version == second.model_version


def test_promotion_gate_rejects_candidate_with_large_divergence():
    registry = ModelRegistry(
        primary=RiskModel("primary", 0, {}),
        candidate=RiskModel("candidate", 0, {}),
        candidate_traffic_percent=10,
    )

    decision = registry.evaluate_promotion(
        sample_count=1_000, mean_absolute_delta=0.08, max_allowed_delta=0.03, minimum_samples=500
    )

    assert decision.promote is False
    assert "exceeds" in decision.reason


async def test_shadow_recorder_buffers_updates_until_flush():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    recorder = ShadowRecorder(client)

    recorder.record(0.01)
    recorder.record(0.03)

    assert await client.hgetall(SHADOW_SUMMARY_KEY) == {}
    await recorder.flush()
    assert await client.hgetall(SHADOW_SUMMARY_KEY) == {
        "sample_count": "2",
        "absolute_delta_sum": "0.04",
    }


async def test_http_api_upserts_and_scores_features():
    from app.api import create_app

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app = create_app(redis_client=client)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http:
        health = await http.get("/healthz")
        inserted = await http.put(
            "/v1/features/customer-2",
            json={
                "transaction_count_1h": 2,
                "amount_sum_24h": 40,
                "account_age_days": 30,
                "country_risk_score": 0.1,
            },
        )
        scored = await http.post(
            "/v1/score", json={"customer_id": "customer-2", "request_id": "test-2"}
        )
        gate = await http.get("/v1/models/candidate/promotion-check")

    assert health.status_code == 200
    assert inserted.status_code == 204
    assert scored.status_code == 200
    assert scored.json()["shadow"]["absolute_delta"] >= 0
    assert "latency_ms" not in scored.json()
    assert scored.json()["inference_latency_ms"] >= 0
    assert scored.headers["server-timing"].startswith("app;dur=")
    assert gate.status_code == 200
    assert gate.json()["sample_count"] == 1
    assert gate.json()["promote"] is False
