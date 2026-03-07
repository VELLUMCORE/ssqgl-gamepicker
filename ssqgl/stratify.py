from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from .models import Candidate

@dataclass(frozen=True)
class StratumKey:
    genre: str
    popularity_bin: int
    source: str

def pick_primary_genre(c: Candidate) -> str:
    if c.genres:
        return c.genres[0]
    return "Unknown"

def compute_popularity_bins(candidates: List[Candidate], k: int) -> Dict[str, int]:
    if k <= 1:
        return {c.id: 0 for c in candidates}
    
    counts = [c.steam_review_count for c in candidates if c.steam_review_count is not None]
    counts_sorted = sorted(int(x) for x in counts) if counts else []
    if not counts_sorted:
        mid = k // 2
        return {c.id: mid for c in candidates}
    
    thresholds: List[int] = []
    n = len(counts_sorted)
    for i in range(1, k):
        idx = int(round((i / k) * (n-1)))
        thresholds.append(counts_sorted[idx])
    
    out: Dict[str, int] = {}
    mid = k // 2
    for c in candidates:
        rc = c.steam_review_count
        if rc is None:
            out[c.id] = mid
            continue
        v = int(rc)
        b = 0
        while b < len(thresholds) and v > thresholds[b]:
            b += 1
        out[c.id] = min(k - 1, b)
    return out

def assign_strata(candidates: List[Candidate], popularity_bins: int) -> Dict[str, StratumKey]:
    pop_map = compute_popularity_bins(candidates, popularity_bins)
    out: Dict[str, StratumKey] = {}
    for c in candidates:
        out[c.id] = StratumKey(
            genre = pick_primary_genre(c),
            popularity_bin = pop_map.get(c.id, 0),
            source = c.source,
        )
    return out

def group_by_stratum(candidates: List[Candidate], strata: Dict[str, StratumKey]) -> Dict[StratumKey, List[Candidate]]:
    groups: Dict[StratumKey, List[Candidate]] = {}
    for c in candidates:
        k = strata[c.id]
        groups.setdefault(k, []).append(c)
    return groups