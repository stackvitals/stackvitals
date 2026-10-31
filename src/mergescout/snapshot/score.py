from dataclasses import dataclass


@dataclass(frozen=True)
class Weights:
    # Architecture §6 until calibrated odds exist; every number here is config, not a law.
    availability: float = 0.30
    outsider_merge: float = 0.30
    reply: float = 0.15
    fixed_before: float = 0.10
    issue_quality: float = 0.15
    prior_merge: float = 0.2
    prior_reply: float = 0.3
    prior_fixed: float = 0.3
    reply_half_hours: float = 48.0
    dead_end: float = 0.8
    dead_end_floor: float = 0.5
    crowded_interest: int = 3
    crowded: float = 0.7
    blocking_wall: float = 0.85
    freshness_half_days: float = 30.0
    discussion: float = 0.3
    untriaged: float = 0.6
    old_days: int = 365
    old: float = 0.75
    very_old_days: int = 730
    very_old: float = 0.5


WEIGHTS = Weights()
