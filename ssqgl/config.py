from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SeedPolicy:
    template: str = "{date}|{phrase}"
    phrase: str = "default"


@dataclass
class SnapshotConfig:
    # shortlist is the *only* pool that gets fully enriched, to avoid "enrich bias"
    shortlist_size: int = 1200
    seed_suffix: str = "|snapshot"
    # how many from each source (ratios; will auto-rebalance if a source is short)
    source_mix: Dict[str, float] = field(default_factory=lambda: {"steam": 0.7, "gog": 0.3})


@dataclass
class SteamSourceConfig:
    enabled: bool = True
    api_key_env: str = "STEAM_WEB_API_KEY"
    appids: List[int] = field(default_factory=list)  # legacy/manual
    discovery: Dict[str, Any] = field(default_factory=dict)
    enrich: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GogSourceConfig:
    enabled: bool = False
    discovery: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LocalSourceConfig:
    enabled: bool = False
    path: Optional[str] = None


@dataclass
class SourcesConfig:
    steam: SteamSourceConfig = field(default_factory=SteamSourceConfig)
    gog: GogSourceConfig = field(default_factory=GogSourceConfig)
    local: LocalSourceConfig = field(default_factory=LocalSourceConfig)
    itch: Dict[str, Any] = field(default_factory=dict)
    metacritic: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FiltersConfig:
    exclude_tags: List[str] = field(default_factory=list)
    exclude_app_types: List[str] = field(default_factory=list)


@dataclass
class QualityGateSteam:
    wilson_lb_min: float = 0.75
    min_reviews: int = 200


@dataclass
class QualityGateConfig:
    explore_mass: float = 0.20
    steam: QualityGateSteam = field(default_factory=QualityGateSteam)
    metascore_min: int = 70


@dataclass
class StratifyConfig:
    popularity_bins: int = 3
    genre_floor_eps: float = 0.02


@dataclass
class WeightsConfig:
    wQ: float = 0.55
    wS: float = 0.30
    wN: float = 0.10
    wC: float = 0.05
    temperature: float = 0.70


@dataclass
class AppConfig:
    cycle: str = "weekly"
    seed_policy: SeedPolicy = field(default_factory=SeedPolicy)
    snapshot: SnapshotConfig = field(default_factory=SnapshotConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    filters: FiltersConfig = field(default_factory=FiltersConfig)
    quality_gate: QualityGateConfig = field(default_factory=QualityGateConfig)
    stratify: StratifyConfig = field(default_factory=StratifyConfig)
    weights: WeightsConfig = field(default_factory=WeightsConfig)

    def to_raw_dict(self) -> Dict[str, Any]:
        return json.loads(json.dumps(self, default=lambda o: o.__dict__, ensure_ascii=False))

    def fingerprint(self) -> str:
        raw = self.to_raw_dict()
        blob = json.dumps(raw, sort_keys=True, ensure_ascii=False).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()


def load_config(path: str) -> AppConfig:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    cfg = AppConfig()

    if "cycle" in data:
        cfg.cycle = str(data["cycle"])

    sp = data.get("seed_policy", {})
    if isinstance(sp, dict):
        cfg.seed_policy.template = sp.get("template", cfg.seed_policy.template)
        cfg.seed_policy.phrase = sp.get("phrase", cfg.seed_policy.phrase)

    snap = data.get("snapshot", {})
    if isinstance(snap, dict):
        cfg.snapshot.shortlist_size = int(snap.get("shortlist_size", cfg.snapshot.shortlist_size))
        cfg.snapshot.seed_suffix = str(snap.get("seed_suffix", cfg.snapshot.seed_suffix))
        sm = snap.get("source_mix", cfg.snapshot.source_mix)
        if isinstance(sm, dict) and sm:
            cfg.snapshot.source_mix = {str(k): float(v) for k, v in sm.items()}

    sources = data.get("sources", {})
    if isinstance(sources, dict):
        steam = sources.get("steam", {})
        if isinstance(steam, dict):
            cfg.sources.steam.enabled = bool(steam.get("enabled", cfg.sources.steam.enabled))
            cfg.sources.steam.api_key_env = steam.get("api_key_env", cfg.sources.steam.api_key_env)
            if isinstance(steam.get("appids"), list):
                cfg.sources.steam.appids = [int(x) for x in steam["appids"]]
            if isinstance(steam.get("discovery"), dict):
                cfg.sources.steam.discovery = steam["discovery"]
            if isinstance(steam.get("enrich"), dict):
                cfg.sources.steam.enrich = steam["enrich"]

        gog = sources.get("gog", {})
        if isinstance(gog, dict):
            cfg.sources.gog.enabled = bool(gog.get("enabled", cfg.sources.gog.enabled))
            if isinstance(gog.get("discovery"), dict):
                cfg.sources.gog.discovery = gog["discovery"]

        local = sources.get("local", {})
        if isinstance(local, dict):
            cfg.sources.local.enabled = bool(local.get("enabled", cfg.sources.local.enabled))
            cfg.sources.local.path = local.get("path", cfg.sources.local.path)

        cfg.sources.itch = sources.get("itch", cfg.sources.itch) or {}
        cfg.sources.metacritic = sources.get("metacritic", cfg.sources.metacritic) or {}

    flt = data.get("filters", {})
    if isinstance(flt, dict):
        if isinstance(flt.get("exclude_tags"), list):
            cfg.filters.exclude_tags = [str(x) for x in flt["exclude_tags"]]
        if isinstance(flt.get("exclude_app_types"), list):
            cfg.filters.exclude_app_types = [str(x) for x in flt["exclude_app_types"]]

    qg = data.get("quality_gate", {})
    if isinstance(qg, dict):
        cfg.quality_gate.explore_mass = float(qg.get("explore_mass", cfg.quality_gate.explore_mass))
        if isinstance(qg.get("steam"), dict):
            st = qg["steam"]
            cfg.quality_gate.steam.wilson_lb_min = float(st.get("wilson_lb_min", cfg.quality_gate.steam.wilson_lb_min))
            cfg.quality_gate.steam.min_reviews = int(st.get("min_reviews", cfg.quality_gate.steam.min_reviews))
        cfg.quality_gate.metascore_min = int(qg.get("metascore_min", cfg.quality_gate.metascore_min))

    stf = data.get("stratify", {})
    if isinstance(stf, dict):
        cfg.stratify.popularity_bins = int(stf.get("popularity_bins", cfg.stratify.popularity_bins))
        cfg.stratify.genre_floor_eps = float(stf.get("genre_floor_eps", cfg.stratify.genre_floor_eps))

    w = data.get("weights", {})
    if isinstance(w, dict):
        cfg.weights.wQ = float(w.get("wQ", cfg.weights.wQ))
        cfg.weights.wS = float(w.get("wS", cfg.weights.wS))
        cfg.weights.wN = float(w.get("wN", cfg.weights.wN))
        cfg.weights.wC = float(w.get("wC", cfg.weights.wC))
        cfg.weights.temperature = float(w.get("temperature", cfg.weights.temperature))

    if cfg.snapshot.shortlist_size < 1:
        raise ValueError("snapshot.shortlist_size must be >= 1")
    if not (0.0 <= cfg.quality_gate.explore_mass <= 1.0):
        raise ValueError("quality_gate.explore_mass must be within [0, 1]")
    if cfg.stratify.popularity_bins < 1:
        raise ValueError("stratify.popularity_bins must be >= 1")
    if cfg.weights.temperature <= 0:
        raise ValueError("weights.temperature must be > 0")

    return cfg


def get_env(name: str) -> Optional[str]:
    v = os.getenv(name)
    return v if v else None