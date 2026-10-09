"""Seed only synthetic features for local demonstrations and load tests."""

import asyncio
import os
import random
import time

import redis.asyncio as redis


async def main() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    count = int(os.getenv("SEED_CUSTOMERS", "10000"))
    ttl_seconds = int(os.getenv("FEATURE_TTL_SECONDS", "900"))
    randomizer = random.Random(20260815)
    client = redis.from_url(redis_url, decode_responses=True)
    now_ms = time.time() * 1000
    try:
        for offset in range(0, count, 500):
            async with client.pipeline(transaction=False) as pipe:
                for index in range(offset, min(offset + 500, count)):
                    payload = {
                        "transaction_count_1h": randomizer.randint(0, 25),
                        "amount_sum_24h": round(randomizer.expovariate(1 / 125), 2),
                        "account_age_days": randomizer.randint(1, 3650),
                        "country_risk_score": round(randomizer.random(), 3),
                        "updated_at_ms": now_ms,
                    }
                    key = f"customer:customer-{index}:features"
                    pipe.hset(key, mapping=payload)
                    pipe.expire(key, ttl_seconds)
                await pipe.execute()
    finally:
        await client.aclose()
    print(f"Seeded {count} synthetic customers into {redis_url}")


if __name__ == "__main__":
    asyncio.run(main())
