from __future__ import annotations

import math
from datetime import date
from typing import Optional, Tuple

from .models import Candidate
from .config import WeightsConfig

def wilson_lower_bound(pos: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    phat = pos / n
    denom = 1 + (z * z) / n
    centre = phat + (z * z) / (2 * n)
    adj = z * math.sqrt((phat * (1 - phat) + (z * z) / (4 * n)) / n)
    return max(0.0, (centre - adj) / denom)

def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))

def score_quality_steam(c: Candidate) -> Optional[float]:
    if c.steam_review_count is None or c.steam_positive_ratio is None:
        return None
    n = int(c.steam_review_count)
    pr = float(c.steam_positive_ratio)
    pos = int(round(pr * n))
    return clamp01(wilson_lower_bound(pos, n))

def score_metascore(c: Candidate) -> Optional[float]:
    if c.metascore is None:
        return None
    return clamp01(float(c.metascore) / 100.0)

def score_novelty(c: Candidate, today: Optional[date] = None) -> Optional[float]:
    if c.release_date is None:
        return None
    if today is None:
        today = date.today()
    days = (today - c.release_date).days
    if days < 0:
        days = 0
    hl = 365.0
    return clamp01(math.exp(-days / hl))

def score_coverage_longtail(c: Candidate) -> Optional[float]:
    if c.steam_review_count is None:
        return None
    n = max(0, int(c.steam_review_count))
    return clamp01(1.0 / (1.0 + math.log10(10 + n)))

def compute_utility(
    c: Candidate,
    weights: WeightsConfig,
    today: Optional[date] = None,
) -> Tuple[float, dict]:
    q = score_quality_steam(c)
    s = score_metascore(c)
    n = score_novelty(c, today=today)
    cov = score_coverage_longtail(c)

    qv = 0.5 if q is None else q
    sv = 0.5 if s is None else s
    nv = 0.5 if n is None else n
    cv = 0.5 if cov is None else cov

    util = (
        weights.wQ * qv +
        weights.wS * sv +
        weights.wN * nv +
        weights.wC * cv
    )
    util = clamp01(util)

    breakdown = {"Q": qv, "S": sv, "N": nv, "C": cv, "utility": util}
    return util, breakdown