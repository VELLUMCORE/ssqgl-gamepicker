from __future__ import annotations

import json
import math
import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple, Optional

from .config import AppConfig
from .models import Candidate, Snapshot
from .scoring import compute_utility, wilson_lower_bound
from .stratify import assign_strata, group_by_stratum, StratumKey


@dataclass
class PickResult:
    picked: Candidate
    seed: str
    gate: str
    stratum: StratumKey
    utility: float
    breakdown: dict
    ranked_ids: List[str]  # deterministic weighted order (for "no reroll")
    meta: dict

    def to_dict(self) -> dict:
        return {
            "picked": self.picked.to_dict(),
            "seed": self.seed,
            "gate": self.gate,
            "stratum": {
                "genre": self.stratum.genre,
                "popularity_bin": self.stratum.popularity_bin,
                "source": self.stratum.source,
            },
            "utility": self.utility,
            "breakdown": self.breakdown,
            "ranked_ids": self.ranked_ids,
            "meta": self.meta,
        }


def make_seed(cfg: AppConfig, day: date) -> str:
    return cfg.seed_policy.template.format(date=day.isoformat(), phrase=cfg.seed_policy.phrase)


def seed_to_int(seed: str) -> int:
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(h[:16], 16)  # 64-bit-ish int


def passes_main_gate(c: Candidate, cfg: AppConfig) -> bool:
    # Metascore gate (if present)
    if c.metascore is not None and c.metascore < cfg.quality_gate.metascore_min:
        return False

    # Steam gate (if steam fields exist)
    if c.source == "steam" and c.steam_review_count is not None and c.steam_positive_ratio is not None:
        n = int(c.steam_review_count)
        if n < cfg.quality_gate.steam.min_reviews:
            return False
        pos = int(round(float(c.steam_positive_ratio) * n))
        lb = wilson_lower_bound(pos, n)
        if lb < cfg.quality_gate.steam.wilson_lb_min:
            return False

    return True


def split_gate(candidates: List[Candidate], cfg: AppConfig) -> Tuple[List[Candidate], List[Candidate]]:
    main, explore = [], []
    for c in candidates:
        (main if passes_main_gate(c, cfg) else explore).append(c)
    return main, explore


def build_weighted_permutation(ids: List[str], weights: List[float], seed_int_value: int) -> List[str]:
    """
    Weighted random permutation without replacement (deterministic by seed).
    Efraimidis-Spirakis: key = -log(u)/w, sort ascending.
    """
    import random

    rng = random.Random(seed_int_value)
    keyed = []
    for i, w in zip(ids, weights):
        ww = max(1e-12, float(w))
        u = max(1e-12, rng.random())
        key = -math.log(u) / ww
        keyed.append((key, i))
    keyed.sort(key=lambda x: x[0])
    return [i for _, i in keyed]


def allocate_stratum_mass(
    groups: Dict[StratumKey, List[Candidate]],
    genre_floor_eps: float,
) -> Dict[StratumKey, float]:
    """
    Allocate probability mass across strata.
    - Start proportional to group sizes
    - Apply a small genre floor so each genre has at least eps mass total
    Then normalize.
    """
    total = sum(len(v) for v in groups.values()) or 1
    mass = {k: len(v) / total for k, v in groups.items()}

    # genre totals
    genre_totals: Dict[str, float] = {}
    for k, m in mass.items():
        genre_totals[k.genre] = genre_totals.get(k.genre, 0.0) + m

    # apply floor per genre
    eps = max(0.0, float(genre_floor_eps))
    if eps > 0:
        for g, cur in list(genre_totals.items()):
            if cur >= eps:
                continue
            deficit = eps - cur
            strata = [k for k in groups.keys() if k.genre == g]
            if not strata:
                continue
            per = deficit / len(strata)
            for k in strata:
                mass[k] = mass.get(k, 0.0) + per

    # renormalize
    s = sum(mass.values()) or 1.0
    return {k: v / s for k, v in mass.items()}


def pick_one(
    cfg: AppConfig,
    snapshot: Snapshot,
    day: date,
    seed_override: Optional[str] = None,
) -> PickResult:
    candidates = snapshot.candidates[:]
    if not candidates:
        raise ValueError("Snapshot has no candidates. Add sources, then rebuild snapshot.")

    main, explore = split_gate(candidates, cfg)

    explore_mass = cfg.quality_gate.explore_mass
    main_mass = 1.0 - explore_mass

    # ✅ seed: default or override
    seed = seed_override if seed_override else make_seed(cfg, day)
    seed_int_value = seed_to_int(seed)

    strata = assign_strata(candidates, cfg.stratify.popularity_bins)
    groups = group_by_stratum(candidates, strata)
    stratum_mass = allocate_stratum_mass(groups, cfg.stratify.genre_floor_eps)

    util_map: Dict[str, float] = {}
    breakdown_map: Dict[str, dict] = {}
    for c in candidates:
        u, br = compute_utility(c, cfg.weights, today=day)
        util_map[c.id] = u
        breakdown_map[c.id] = br

    # Build final candidate weights
    ids: List[str] = []
    weights: List[float] = []

    for c in candidates:
        ids.append(c.id)

        gate = "MAIN" if c in main else "EXPLORE"
        gate_mass = main_mass if gate == "MAIN" else explore_mass

        k = strata[c.id]
        sm = stratum_mass.get(k, 0.0)

        # Smooth probability transform so top scores don't monopolize
        u = util_map[c.id]
        local = math.exp(u / max(1e-9, cfg.weights.temperature))

        w = gate_mass * sm * local
        weights.append(max(1e-12, w))

    ranked_ids = build_weighted_permutation(ids, weights, seed_int_value)

    picked_id = ranked_ids[0]
    picked = next(c for c in candidates if c.id == picked_id)

    picked_gate = "MAIN" if picked in main else "EXPLORE"
    picked_stratum = strata[picked.id]
    picked_util = util_map[picked.id]
    picked_breakdown = breakdown_map[picked.id]

    meta = {
        "snapshot_created_at": snapshot.created_at,
        "snapshot_config_fingerprint": snapshot.config_fingerprint,
        "counts": {
            "total": len(candidates),
            "main": len(main),
            "explore": len(explore),
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    return PickResult(
        picked=picked,
        seed=seed,
        gate=picked_gate,
        stratum=picked_stratum,
        utility=picked_util,
        breakdown=picked_breakdown,
        ranked_ids=ranked_ids,
        meta=meta,
    )


def save_run(result: PickResult, out_dir: str) -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    # runs file name based on date-ish token inside seed if possible; otherwise fallback to UTC date
    # keep compatible with previous scheme
    day_token = result.seed.split("|", 1)[0]
    if len(day_token) != 10 or day_token[4] != "-" or day_token[7] != "-":
        day_token = datetime.now(timezone.utc).date().isoformat()

    path = Path(out_dir) / f"{day_token}.pick.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    return str(path)