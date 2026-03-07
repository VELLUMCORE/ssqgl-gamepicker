# SSQGL GamePicker

**언어:** [English](README.md) | 한국어

본인의 의사 결정 없이, 규칙에 따라 무작위로 게임을 뽑는 프로젝트입니다.

이 프로젝트는 **SSQGL(Seeded Stratified Quality-Gated Lottery)** 방식을 구현합니다.
- **Seeded (시드 고정)**: 같은 입력이면 결과가 항상 동일 (재현 가능)
- **Stratified (층화)**: 인기도 쏠림을 줄이고 장르 소회를 방지
- **Quality-gated (품질 게이트)**: 낮은 퀄리티의 게임이 풀을 지배하는 상황을 방지
- **Lottery (추첨)**: 무작위성은 유지하되, 통제 가능하고 설명 가능한 방식

## 왜 SSQGL?

흔한 게임 선정 방식은 문제들이 있습니다.
- "할인 목록에서 뽑기": 같은 게임이 반복되거나 퀄리티 편차가 큼
- "메타크리틱 상위만": 메이저/클래식이 독식하며 롱테일은 못 함
- "스토어에서 무작위로 뽑기": 잡음(저퀄/스팸)이 많음

SSQGL의 목표는 **공정한 다양성 + 최소 품질 + 투명성 + 재현성**입니다.

## 핵심 아이디어
매 회차마다 후보를 수집해 스냅샷으로 저장하여 이번 회차 후보 풀을 고정합니다.
후보를 **MAIN** (품질 기준 통과)과 **EXPLORE** (데이터 부족/신작/니치/롱테일)로 나누고, EXPLORE에는 고정된 확률 질량(예: 20%)만 배정합니다.
그 다음 후보를 **장르 x 인기도 구간 x 출처**로 층화하고, 각 층에 선택 확률을 배분하되 장르 바닥값을 둬서 특정 장르 확률이 0이 되지 않게 합니다.
마지막으로 시드 고정 가중 추첨을 수행하되, temperature/softmax같은 완만한 확률 변환을 적용해 상위 점수가 전부 가져가는 현상을 줄입니다.

## 기능
- ✅ Provider 구조로 후보 수집 (예: Steam / GOG / itch.io / Metacritic)
- ✅ 스냅샷 기반 회차 운영 (회차별 후보 풀 고정)
- ✅ 품질 게이트 (MAIN + EXPLORE)
- ✅ 층화로 인기도 편향/장르 소외 완화
- ✅ 시드로 결과 재현 가능
- ✅ 이 게임이 뽑힌 이유 출력
- ✅ "재추첨 금지" 규칙: 선정된 게임에 문제 발생 시 **같은 시드 순서에서 다음 후보**를 채택

## 설치

### 요구사항
- Python 3.11+

### 로컬 실행
```bash
git clone https://github.com/VELLUMCORE/ssqgl-gamepicker.git
cd ssqgl-gamepicker
python -m venv .venv
# Windows: .venv/Scripts/activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

### 빠른 시작
1) 설정 파일 만들기
`config.json` 예시
```json
{
  "cycle": "weekly",
  "seed_policy": {
    "template": "{date}|{phrase}",
    "phrase": "example"
  },
  "sources": {
    "steam": { "enabled": true, "api_key_env": "STEAM_WEB_API_KEY" },
    "itch": { "enabled": false, "api_key_env": "ITCH_API_KEY" },
    "gog": { "enabled": false },
    "metacritic": { "enabled": false" }
  },
  "filters": {
    "exclude_tags": ["Horror"],
    "exclude_app_types": ["DLC", "Soundtrack", "Tool"]
  },
  "quality_gate": {
    "explore_mass": 0.20,
    "steam": { "wilson_1b_min": 0.75, "min_reviews": 200 },
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
기존 설정에서 아무것도 건들이지 않아도 됩니다.

2) 후보 스냅샷 생성
```bash
python -m ssqgl snapshot --config config.json --out snapshots/
```
--out에 지정한 경로에 스냅샷이 생성됩니다.

3) 게임 1개 선정
```bash
python -m ssqgl pick --config config.json --snapshot snapshots/2026-03-01.json
```
--config과 --snapshot을 기준으로 게임을 선정합니다.

출력 예시:
```plain text
✅ Picked: Example Game
- Source: Steam
- Stratum: (Action, popularity=mid, source=steam)
- Gate: MAIN
- Utility: 0.812 (Q=0.76, S=0.90, N=0.45, C=0.80)
- Seed: 2026-03-01|example
Saved: runs/2026-03-01.pick.json
```
