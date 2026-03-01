# SSQGL GamePicker

A **rule-driven** "game of the day" picker for people who hate feeling like they *personally* chose the game.

This project implements **SSQGL (Seeded Stratified Quality-Gated Lottery)**:
- **Seeded**: the same input always produce the same pick (reproducible).
- **Stratified**: prevents "only popular games" and reduces genre starvation.
- **Quality-gated**: avoids low-quality picks dominating the pool.
- **Lottery**: still random, but controlled and explainable.

---

## Why SSQGL?

Common selectors fail in predictable ways:
- "Pick from discount lists": repeats and often low-quality
- "Play top Metacritic": repeats mainstream classics and ignores the long tail.
- "Pure random from store": too many shovelware / noisy results.

SSQGL aims for **fair variety + minimum quality + transperency + reproducibility**.

---

## Core idea
Each cycle, the app builds a **snapshot** of candidates (so the pool is fixed for that cycle).
It splits candidates into **MAIN** (passes a quality threshold) and **EXPLORE** (data-poor/new/long-tail items) with a fixed probability mass (e.g. 20%).
Then it **stratifies** candidates by **genre x popularity bin x source**, allocates selection mass per stratum (with a small "genre floor" so no genre goes to 0), and performs a **seeded weighted draw** using a softened probability transform (temperature/softmax) so top scores don't completely dominate.

---

## Features

- ✅ Provider-based ingestion (Steam / GOG / itch.io / Metacritic, etc.)
- ✅ Snapshot-based cycles (stable pool per run)
- ✅ Quality gate (MAIN + EXPLORE pool)
- ✅ Stratification to reduce popularity bias and genre starvation
- ✅ Seeded results (fully reproducible)
- ✅ Explainable output (why this game was picked)
- ✅ "No reroll" rule: if the chosen title is unplayable, pick the next candidate **in the same seeded order**

---

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
