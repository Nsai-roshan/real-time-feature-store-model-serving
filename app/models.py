from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskModel:
    version: str
    intercept: float
    weights: dict[str, float]

    def predict(self, features: dict[str, float]) -> float:
        logit = self.intercept + sum(
            self.weights.get(name, 0.0) * value for name, value in features.items()
        )
        logit = max(-35.0, min(35.0, logit))
        return 1.0 / (1.0 + math.exp(-logit))


@dataclass(frozen=True)
class PromotionDecision:
    promote: bool
    reason: str


class ModelRegistry:
    def __init__(
        self, primary: RiskModel, candidate: RiskModel, candidate_traffic_percent: int
    ) -> None:
        if not 0 <= candidate_traffic_percent <= 100:
            raise ValueError("candidate_traffic_percent must be from 0 to 100")
        self.primary = primary
        self.candidate = candidate
        self.candidate_traffic_percent = candidate_traffic_percent

    def select(self, request_id: str) -> tuple[RiskModel, RiskModel]:
        bucket = int(hashlib.sha256(request_id.encode()).hexdigest()[:8], 16) % 100
        if bucket < self.candidate_traffic_percent:
            return self.candidate, self.primary
        return self.primary, self.candidate

    def evaluate_promotion(
        self,
        sample_count: int,
        mean_absolute_delta: float,
        max_allowed_delta: float,
        minimum_samples: int,
    ) -> PromotionDecision:
        if sample_count < minimum_samples:
            return PromotionDecision(
                False, f"insufficient samples: {sample_count} < {minimum_samples}"
            )
        if mean_absolute_delta > max_allowed_delta:
            return PromotionDecision(
                False,
                f"mean absolute delta {mean_absolute_delta:.4f} exceeds {max_allowed_delta:.4f}",
            )
        return PromotionDecision(True, "candidate meets shadow comparison gate")
