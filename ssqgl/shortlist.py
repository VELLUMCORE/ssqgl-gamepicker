from __future__ import annotations

import hashlib
import logging
import math
import random
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Tuple

from .config import AppConfig
from .models import Candidate

log = logging.getLogger("ssqgl.shortlist")


@dataclass(frozen=True)
class ShortStratum:
    genre_label: str
    pop_bin: int


def _seed_int(seed: str) -> int:
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return int(h[:16], 16)


def make_snapshot_seed(cfg: AppConfig, day: date) -> str:
    base = cfg.seed_policy.template.format(date=day.isoformat(), phrase=cfg.seed_policy.phrase)
    return base + cfg.snapshot.seed_suffix


def _pop_bin(c: Candidate) -> int:
    # discovery-time popularity hint: 0=front/popular, 1=mid, 2=deep/longtail
    v = None
    if isinstance(c.raw, dict):
        v = c.raw.get("pop_hint")
    try:
        vv = int(v)
        return 0 if vv < 0 else (2 if vv > 2 else vv)
    except Exception:
        return 1


def _genre_label(c: Candidate) -> str:
    # discovery uses a "label genre" (channel label); enrich later overwrites with real genres
    if c.genres:
        return str(c.genres[0])
    return "Unknown"


def _allocate_stratum_mass(groups: Dict[ShortStratum, List[Candidate]], genre_floor_eps: float) -> Dict[ShortStratum, float]:
    # base mass proportional to group sizes
    total = sum(len(v) for v in groups.values()) or 1
    mass = {k: len(v) / total for k, v in groups.items()}

    # apply a small genre floor so genres don't go to 0
    eps = max(0.0, float(genre_floor_eps))
    if eps > 0:
        genre_totals: Dict[str, float] = {}
        for k, m in mass.items():
            genre_totals[k.genre_label] = genre_totals.get(k.genre_label, 0.0) + m

        for g, cur in list(genre_totals.items()):
            if cur >= eps:
                continue
            deficit = eps - cur
            strata = [k for k in groups.keys() if k.genre_label == g]
            if not strata:
                continue
            add = deficit / len(strata)
            for k in strata:
                mass[k] = mass.get(k, 0.0) + add

    s = sum(mass.values()) or 1.0
    return {k: v / s for k, v in mass.items()}


def _weighted_permutation(ids: List[str], weights: List[float], seed_int_value: int) -> List[str]:
    # Efraimidis–Spirakis: key=-log(u)/w ; sort ascending
    rng = random.Random(seed_int_value)
    keyed: List[Tuple[float, str]] = []
    for i, w in zip(ids, weights):
        ww = max(1e-12, float(w))
        u = max(1e-12, rng.random())
        key = -math.log(u) / ww
        keyed.append((key, i))
    keyed.sort(key=lambda x: x[0])
    return [i for _, i in keyed]


def _stratified_pick(
    candidates: List[Candidate],
    n: int,
    seed_int_value: int,
    genre_floor_eps: float,
) -> List[Candidate]:
    if n <= 0 or not candidates:
        return []

    # group by discovery label + pop hint
    groups: Dict[ShortStratum, List[Candidate]] = {}
    for c in candidates:
        k = ShortStratum(_genre_label(c), _pop_bin(c))
        groups.setdefault(k, []).append(c)

    stratum_mass = _allocate_stratum_mass(groups, genre_floor_eps=genre_floor_eps)

    ids: List[str] = []
    weights: List[float] = []

    # Equal within stratum: stratum mass is divided by stratum size
    for k, items in groups.items():
        per = stratum_mass.get(k, 0.0) / max(1, len(items))
        for c in items:
            ids.append(c.id)
            weights.append(max(1e-12, per))

    ranked_ids = _weighted_permutation(ids, weights, seed_int_value)
    chosen = set(ranked_ids[: min(n, len(ranked_ids))])
    out = [c for c in candidates if c.id in chosen]
    out.sort(key=lambda c: ranked_ids.index(c.id))
    return out


def build_shortlist(cfg: AppConfig, discovered: List[Candidate], day: date, genre_floor_eps: float) -> List[Candidate]:
    seed = make_snapshot_seed(cfg, day)
    s_int = _seed_int(seed)

    # partition by source
    by_source: Dict[str, List[Candidate]] = {}
    for c in discovered:
        by_source.setdefault(c.source, []).append(c)

    size = cfg.snapshot.shortlist_size
    mix = cfg.snapshot.source_mix or {"steam": 1.0}

    # normalize mix over available sources
    total_w = sum(float(mix.get(src, 0.0)) for src in by_source.keys())
    if total_w <= 0:
        mix = {src: 1.0 for src in by_source.keys()}
        total_w = sum(mix.values())

    quotas: Dict[str, int] = {}
    remaining = size
    sources = sorted(by_source.keys())
    for src in sources:
        w = float(mix.get(src, 0.0))
        q = int(round(size * (w / total_w))) if total_w > 0 else 0
        q = max(0, min(q, len(by_source[src])))
        quotas[src] = q
        remaining -= q

    # redistribute leftover (because rounding/shortage)
    # deterministic: iterate sources by availability
    if remaining > 0:
        for src in sorted(sources, key=lambda s: len(by_source[s]) - quotas[s], reverse=True):
            if remaining <= 0:
                break
            cap = len(by_source[src]) - quotas[src]
            if cap <= 0:
                continue
            add = min(cap, remaining)
            quotas[src] += add
            remaining -= add

    log.info("Shortlist plan | size=%d seed=%s", size, seed)
    log.info("Shortlist quotas | %s", {k: quotas[k] for k in quotas})

    chosen: List[Candidate] = []
    for src in sources:
        pool = by_source[src]
        n = quotas.get(src, 0)
        if n <= 0:
            continue
        # per-source seed offset
        src_seed = s_int ^ _seed_int(src)
        part = _stratified_pick(pool, n=n, seed_int_value=src_seed, genre_floor_eps=genre_floor_eps)
        chosen.extend(part)

    # final stable order (by seeded rank across all chosen)
    # give each chosen candidate a stable key derived from seed+id
    chosen.sort(key=lambda c: _seed_int(seed + "|" + c.id))

    log.info("Shortlist built | chosen=%d (from discovered=%d)", len(chosen), len(discovered))
    return chosen