# SSQGL GamePicker

**Languages:** English | [한국어](README.ko.md)

A **rule-driven** "game of the day" picker for people who hate feeling like they *personally* chose the game.

This project implements **SSQGL (Seeded Stratified Quality-Gated Lottery)**:
- **Seeded**: the same input always produce the same pick (reproducible).
- **Stratified**: prevents "only popular games" and reduces genre starvation.
- **Quality-gated**: avoids low-quality picks dominating the pool.
- **Lottery**: still random, but controlled and explainable.

## Why SSQGL?

Common selectors fail in predictable ways:
- "Pick from discount lists": repeats and often low-quality
- "Play top Metacritic": repeats mainstream classics and ignores the long tail.
- "Pure random from store": too many shovelware / noisy results.

SSQGL aims for **fair variety + minimum quality + transperency + reproducibility**.

## Core idea
Each cycle, the app builds a **snapshot** of candidates (so the pool is fixed for that cycle).
It splits candidates into **MAIN** (passes a quality threshold) and **EXPLORE** (data-poor/new/long-tail items) with a fixed probability mass (e.g. 20%).
Then it **stratifies** candidates by **genre x popularity bin x source**, allocates selection mass per stratum (with a small "genre floor" so no genre goes to 0), and performs a **seeded weighted draw** using a softened probability transform (temperature/softmax) so top scores don't completely dominate.

## Features

- ✅ Provider-based ingestion (Steam / GOG / itch.io / Metacritic, etc.)
- ✅ Snapshot-based cycles (stable pool per run)
- ✅ Quality gate (MAIN + EXPLORE pool)
- ✅ Stratification to reduce popularity bias and genre starvation
- ✅ Seeded results (fully reproducible)
- ✅ Explainable output (why this game was picked)
- ✅ "No reroll" rule: if the chosen title is unplayable, pick the next candidate **in the same seeded order**

## Installation

### Requirements
- Python 3.11+

### Local setup
```bash
git clone https://github.com/VELLUMCORE/ssqgl-gamepicker.git
cd ssqgl-gamepicker
python -m venv .venv
# Windows: .venv/Scripts/activate
# macOS/Linux: source .vnev/bin/activate
pip install -r requirements.txt
```

### Quick start
1) Create a config
Example `config.json`
```json
{
  "cycle": "weekly",
  "seed_policy": {
    "template": "{date}|{phrase}",
    "phrase": "byulger"
  },
  "sources": {
    "steam": { "enabled": true, "api_key_env": "STEAM_WEB_API_KEY" },
    "itch":  { "enabled": false, "api_key_env": "ITCH_API_KEY" },
    "gog":   { "enabled": false },
    "metacritic": { "enabled": false }
  },
  "filters": {
    "exclude_tags": ["Horror"],
    "exclude_app_types": ["DLC", "Soundtrack", "Tool"]
  },
  "quality_gate": {
    "explore_mass": 0.20,
    "steam": { "wilson_lb_min": 0.75, "min_reviews": 200 },
    "metacritic": { "metascore_min": 70 }
  },
  "stratify": {
    "popularity_bins": 3,
    "genre_floor_eps": 0.02
  },
  "weights": {
    "wQ": 0.55, "wS": 0.30, "wN": 0.10, "wC": 0.05,
    "temperature": 0.70
  }
}
```

2) Build a snapshot (candidate pool)
```bash
python -m ssqgl snapshot --config config.json --out snapshots/
```

3) Pick a game
```bash
python -m ssqgl pick --config config.json --snapshot snapshots/2026-03-01.json
```

Example output:
```plain text
✅ Picked: Example Game
- Source: Steam
- Stratum: (Action, popularity=mid, source=steam)
- Gate: MAIN
- Utility: 0.812 (Q=0.76 S=0.90 N=0.45 C=0.80)
- Seed: 2026-03-01|example
Saved: runs/2026-03-01.pick.json
```
