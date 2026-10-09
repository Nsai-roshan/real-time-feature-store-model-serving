from __future__ import annotations

import time

FEATURE_NAMES = ("transaction_count_1h", "amount_sum_24h", "account_age_days", "country_risk_score")


class OnlineFeatureStore:
    def __init__(self, client, feature_ttl_seconds: int = 300) -> None:
        self.client = client
        self.feature_ttl_seconds = feature_ttl_seconds

    @staticmethod
    def _key(customer_id: str) -> str:
        return f"customer:{customer_id}:features"

    async def get(self, customer_id: str) -> tuple[dict[str, float], float]:
        values = await self.client.hmget(self._key(customer_id), *FEATURE_NAMES, "updated_at_ms")
        if all(value is None for value in values):
            raise KeyError("customer features not found")
        try:
            features = {name: float(values[index]) for index, name in enumerate(FEATURE_NAMES)}
            age_ms = max(0.0, time.time() * 1000 - float(values[-1]))
        except (TypeError, ValueError) as exc:
            raise ValueError("stored features are invalid") from exc
        return features, age_ms

    async def put(self, customer_id: str, features: dict[str, float]) -> None:
        if set(features) != set(FEATURE_NAMES):
            raise ValueError("feature payload does not match the feature contract")
        key = self._key(customer_id)
        payload = {
            **{name: str(value) for name, value in features.items()},
            "updated_at_ms": str(time.time() * 1000),
        }
        async with self.client.pipeline(transaction=True) as pipe:
            pipe.hset(key, mapping=payload)
            pipe.expire(key, self.feature_ttl_seconds)
            await pipe.execute()
