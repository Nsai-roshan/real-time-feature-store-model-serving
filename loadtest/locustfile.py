import os
import random

from locust import FastHttpUser, constant_throughput, task


class ScoreUser(FastHttpUser):
    """One request/second per user; 1,000 users targets 1,000 RPS."""

    wait_time = constant_throughput(1)

    @task
    def score(self):
        customer = f"customer-{random.randrange(int(os.getenv('SEED_CUSTOMERS', '10000')))}"
        self.client.post(
            "/v1/score",
            json={"customer_id": customer, "request_id": f"load-{random.getrandbits(64)}"},
            name="/v1/score",
        )
