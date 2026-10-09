"""Optional Feast definitions for offline-to-online materialization.

Install `.[feast]` to use `feast apply` and materialize this schema. The serving
path uses the same Redis entity/key contract directly to avoid request-time registry lookups.
"""

from datetime import timedelta

from feast import Entity, FeatureView, Field, FileSource
from feast.types import Float32

customer = Entity(name="customer_id", join_keys=["customer_id"])

customer_source = FileSource(
    name="customer_risk_source",
    path="data/customer_features.parquet",
    timestamp_field="event_timestamp",
)

customer_risk_features = FeatureView(
    name="customer_risk_features",
    entities=[customer],
    ttl=timedelta(minutes=5),
    schema=[
        Field(name="transaction_count_1h", dtype=Float32),
        Field(name="amount_sum_24h", dtype=Float32),
        Field(name="account_age_days", dtype=Float32),
        Field(name="country_risk_score", dtype=Float32),
    ],
    online=True,
    source=customer_source,
)
