from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, date
from pathlib import Path
from typing import List, Optional

from .config import AppConfig
from .models import Candidate, Snapshot
from .providers.local import LocalProvider
from .providers.steam import steam_discover_candidates, steam_enrich_candidates
from .providers.gog import gog_discover_candidates
from .shortlist import build_shortlist

log = logging.getLogger("ssqgl.snapshot")


def _apply_filters(candidates: List[Candidate], cfg: AppConfig) -> List[Candidate]:
    ex_tags = {t.lower() for t in cfg.filters.exclude_tags}
    ex_types = {t.lower() for t in cfg.filters.exclude_app_types}

    out: List[Candidate] = []
    for c in candidates:
        if c.app_type and c.app_type.lower() in ex_types:
            continue
        # tags + genres both treated as labels for exclusion convenience
        all_labels = [x.lower() for x in (c.tags + c.genres)]
        if any(t in ex_tags for t in all_labels):
            continue
        out.append(c)
    return out


def build_snapshot(cfg: AppConfig, day: Optional[date] = None) -> Snapshot:
    day = day or date.today()

    # 1) Discovery (large, shallow)
    discovered: List[Candidate] = []

    if cfg.sources.steam.enabled:
        discovered.extend(steam_discover_candidates(cfg, day))
    if cfg.sources.gog.enabled:
        discovered.extend(gog_discover_candidates(cfg, day))

    # optional local
    discovered.extend(LocalProvider().fetch(cfg))

    # dedupe by id (keep first; merge discovery logs)
    by_id: dict[str, Candidate] = {}
    for c in discovered:
        if c.id not in by_id:
            by_id[c.id] = c
        else:
            # merge raw.discovery if available
            exist = by_id[c.id]
            if isinstance(exist.raw, dict) and isinstance(c.raw, dict):
                exist.raw.setdefault("discovery", [])
                exist.raw["discovery"].extend(c.raw.get("discovery", []))
                # keep best (lowest) pop_hint
                try:
                    exist.raw["pop_hint"] = min(int(exist.raw.get("pop_hint", 1)), int(c.raw.get("pop_hint", 1)))
                except Exception:
                    pass

    discovered = list(by_id.values())
    counts_disc = _counts_by_source(discovered)
    log.info("Discovery done | total=%d | %s", len(discovered), counts_disc)

    # 2) Shortlist selection (seeded + stratified, per source mix)
    shortlist = build_shortlist(cfg, discovered, day=day, genre_floor_eps=cfg.stratify.genre_floor_eps)
    counts_short = _counts_by_source(shortlist)

    # 3) Enrich ALL shortlist (no enrich bias)
    steam_short = [c for c in shortlist if c.source == "steam"]
    non_steam = [c for c in shortlist if c.source != "steam"]

    steam_enriched, steam_stats = steam_enrich_candidates(cfg, steam_short, day)

    enriched = steam_enriched + non_steam

    # After enrich, apply filters (now genres/types are reliable)
    enriched = _apply_filters(enriched, cfg)

    counts_enriched = _counts_by_source(enriched)
    log.info("Enrich done | total=%d | %s", len(enriched), counts_enriched)

    created_at = datetime.now(timezone.utc).isoformat()
    snap = Snapshot(
        created_at=created_at,
        config_fingerprint=cfg.fingerprint(),
        candidates=enriched,
        notes={
            "day": day.isoformat(),
            "discovered_total": len(discovered),
            "discovered_by_source": counts_disc,
            "shortlist_size": cfg.snapshot.shortlist_size,
            "shortlist_by_source": counts_short,
            "enriched_total": len(enriched),
            "enriched_by_source": counts_enriched,
            "steam_enrich_stats": steam_stats,
        },
    )
    return snap


def _counts_by_source(candidates: List[Candidate]) -> dict:
    out = {}
    for c in candidates:
        out[c.source] = out.get(c.source, 0) + 1
    return out


def save_snapshot(snapshot: Snapshot, out_dir: str) -> str:
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    utc_date = snapshot.created_at.split("T")[0]
    path = Path(out_dir) / f"{utc_date}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(snapshot.to_dict(), f, ensure_ascii=False, indent=2)
    return str(path)