"""썬데이 피처: State + features_from_state로 학습·예측 동일 규칙.

build_features: 주 단위로 state→한 줄→y_* 후 advance.
build_next_features: rows[:-1]까지 advance 후 마지막 주·target_date만 보정."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np

# =============================================================================
# 1) 상수 — ALL_CATEGORIES(태그→버킷), MAIN_CATS(체인·열 순서), PREV_GROUP_*, FEATURE_COLS
#    (순서·이름 바꾸면 저장된 체인과 불일치)
# =============================================================================

ALL_CATEGORIES: dict[str, list[str]] = {
    "사냥": ["룬_콤보킬", "트레져_헌터", "솔에르다_2배", "솔에르다_타임", "현상금_사냥꾼"],
    "몬스터파크": ["몬스터파크"],
    "샤이닝": [
        "샤이닝_스타포스",
        "스타포스_1+1",
        "스타포스_30%할인",
        "스타포스_5_10_15",
        "스타포스_파괴감소",
    ],
    "어빌리티": ["어빌리티_반값"],
    "주흔반값": ["주문의_흔적_반값"],
    "소울": ["소울_확률"],
    "몬컬": ["몬컬_세트"],
    "미라클": ["미라클_타임"],
    "헥사": ["헥사_스텟"],
}

MAIN_CATS: list[str] = [
    "사냥",
    "샤이닝",
    "미라클",
    "몬컬",
    "소울",
    "헥사",
    "어빌리티",
    "주흔반값",
    "몬스터파크",
]

PREV_GROUP_ENHANCE: frozenset[str] = frozenset(
    {"샤이닝", "미라클", "어빌리티", "주흔반값", "소울", "헥사"}
)
PREV_GROUP_HUNT: frozenset[str] = frozenset({"사냥", "몬스터파크"})

# CatBoost 한 행 = MAIN_CATS마다 days_·prev_·prev2_·recent4_ + tail
# days_: 마지막 출현 이후 일수(없으면 365). prev_/prev2_: 직전·직직전 주 0/1(recent4·prev는 predict 시 보정).
# tail: month | event_type(event_type_code) | prev_active_count | prev_enhance_group_count |
#       prev_hunt_group_count | week_in_season | is_challengers_season
_FEATURE_TAIL = [
    "month",
    "event_type",
    "prev_active_count",
    "prev_enhance_group_count",
    "prev_hunt_group_count",
    "week_in_season",
    "is_challengers_season",
]
FEATURE_COLS: tuple[str, ...] = tuple(
    [f"days_{c}" for c in MAIN_CATS]
    + [f"prev_{c}" for c in MAIN_CATS]
    + [f"prev2_{c}" for c in MAIN_CATS]
    + [f"recent4_{c}" for c in MAIN_CATS]
    + _FEATURE_TAIL
)


# =============================================================================
# 2) 전처리 — cat_* 라벨, event tail용 스칼라(event_type_code 등)
# =============================================================================

def add_category_labels(rows: list[dict]) -> list[dict]:
    """원본 태그 행에 cat_<카테고리> 0/1 라벨 붙임. build_features 전에 호출."""
    for row in rows:
        for cat, tags in ALL_CATEGORIES.items():
            row[f"cat_{cat}"] = 1 if any(int(row.get(t, 0)) == 1 for t in tags) else 0
    return rows


def event_type_code(ev: str | None) -> int:
    """event 문자열 접두: < → 1, ( → 0, 그 외 -1 (_FEATURE_TAIL event_type)."""
    s = (ev or "").strip()
    if s.startswith("<"):
        return 1
    if s.startswith("("):
        return 0
    return -1


def challengers_season_flag(ev: str | None) -> int:
    """이벤트명에 '챌린저스' 포함 시 1 (is_challengers_season)."""
    return 1 if "챌린저스" in (ev or "").strip() else 0


# =============================================================================
# 3) State 스캔 — State / advance_state / features_from_state (주 누적 → FEATURE_COLS 한 줄)
# =============================================================================

@dataclass
class State:
    last_seen: dict[str, datetime | None] = field(default_factory=dict)
    prev_label: dict[str, int] = field(default_factory=dict)
    prev2_label: dict[str, int] = field(default_factory=dict)
    recent_window: list[dict[str, int]] = field(default_factory=list)
    prev_event: str | None = None
    week_in_season: int = 0

    @classmethod
    def initial(cls, cats: list[str]) -> "State":
        return cls(
            last_seen={c: None for c in cats},
            prev_label={c: 0 for c in cats},
            prev2_label={c: 0 for c in cats},
            recent_window=[],
            prev_event=None,
            week_in_season=0,
        )


def advance_state(state: State, row: dict, cats: list[str]) -> State:
    dt = row["_dt"]
    ev = (row.get("event") or "(-)").strip()
    this_labels = {c: int(row[f"cat_{c}"]) for c in cats}

    new_last_seen = dict(state.last_seen)
    for c in cats:
        if this_labels[c] == 1:
            new_last_seen[c] = dt

    new_prev2 = dict(state.prev_label)
    new_prev = this_labels

    new_window = list(state.recent_window) + [this_labels]
    if len(new_window) > 4:
        new_window = new_window[-4:]

    if state.prev_event is None:
        new_wis = 1
    elif ev != state.prev_event:
        new_wis = 1
    else:
        new_wis = state.week_in_season + 1

    return State(
        last_seen=new_last_seen,
        prev_label=new_prev,
        prev2_label=new_prev2,
        recent_window=new_window,
        prev_event=ev,
        week_in_season=new_wis,
    )


def features_from_state(
    state: State,
    dt: datetime,
    event: str,
    cats: list[str],
) -> dict[str, Any]:
    f: dict[str, Any] = {}

    for cat in cats:
        last = state.last_seen.get(cat)
        if last is None:
            f[f"days_{cat}"] = 365
        else:
            f[f"days_{cat}"] = (dt - last).days

    for cat in cats:
        f[f"prev_{cat}"] = int(state.prev_label.get(cat, 0))

    for cat in cats:
        f[f"prev2_{cat}"] = int(state.prev2_label.get(cat, 0))

    for cat in cats:
        count = 0
        for wk in state.recent_window:
            count += int(wk.get(cat, 0))
        f[f"recent4_{cat}"] = count

    f["month"] = dt.month
    f["event_type"] = event_type_code(event)

    f["prev_active_count"] = sum(1 for c in cats if int(state.prev_label.get(c, 0)) == 1)

    f["prev_enhance_group_count"] = sum(
        1 for c in cats if c in PREV_GROUP_ENHANCE and int(state.prev_label.get(c, 0)) == 1
    )
    f["prev_hunt_group_count"] = sum(
        1 for c in cats if c in PREV_GROUP_HUNT and int(state.prev_label.get(c, 0)) == 1
    )

    if state.prev_event is None or event.strip() != (state.prev_event or ""):
        f["week_in_season"] = 1
    else:
        f["week_in_season"] = state.week_in_season + 1

    f["is_challengers_season"] = challengers_season_flag(event)

    return f


# =============================================================================
# 4) 진입점 — build_features(학습 전체) · build_next_features(다음 일 1행) · matrix_from_rows
# =============================================================================

def build_features(rows: list[dict], cats: list[str]) -> list[dict]:
    """학습용 주별 dict 리스트. FEATURE_COLS + _dt, date, event, y_*."""
    state = State.initial(cats)
    out: list[dict] = []
    for row in rows:
        dt = row["_dt"]
        ev = (row.get("event") or "(-)").strip()

        f = features_from_state(state, dt, ev, cats)
        f["_dt"] = dt
        f["date"] = row["date"]
        f["event"] = ev
        for cat in cats:
            f[f"y_{cat}"] = int(row[f"cat_{cat}"])

        out.append(f)
        state = advance_state(state, row, cats)

    return out


def build_next_features(
    rows: list[dict],
    cats: list[str],
    target_date: datetime,
) -> dict[str, Any]:
    """다음 일요일 1행. rows[:-1]까지 state 반영 후 last_row 기준으로 prev/days/week 보정."""
    if not rows:
        return features_from_state(State.initial(cats), target_date, "(-)", cats)

    last_row = rows[-1]
    last_event = (last_row.get("event") or "(-)").strip()
    last_dt = last_row["_dt"]
    gap = (target_date - last_dt).days

    state = State.initial(cats)
    for r in rows[:-1]:
        state = advance_state(state, r, cats)

    f = features_from_state(state, last_dt, last_event, cats)

    for cat in cats:
        f[f"prev2_{cat}"] = int(f[f"prev_{cat}"])
    for cat in cats:
        f[f"prev_{cat}"] = int(last_row[f"cat_{cat}"])

    for cat in cats:
        if int(last_row[f"cat_{cat}"]) == 1:
            f[f"days_{cat}"] = gap
        else:
            f[f"days_{cat}"] = int(f[f"days_{cat}"]) + gap

    f["prev_active_count"] = sum(1 for c in cats if int(last_row[f"cat_{c}"]) == 1)
    f["prev_enhance_group_count"] = sum(
        1 for c in cats if c in PREV_GROUP_ENHANCE and int(last_row[f"cat_{c}"]) == 1
    )
    f["prev_hunt_group_count"] = sum(
        1 for c in cats if c in PREV_GROUP_HUNT and int(last_row[f"cat_{c}"]) == 1
    )

    f["week_in_season"] = int(f["week_in_season"]) + max(1, gap // 7)

    f["month"] = target_date.month

    return f


def matrix_from_rows(rows: list[dict], cols: tuple[str, ...] = FEATURE_COLS) -> np.ndarray:
    """dict 리스트를 CatBoost 입력 행렬로 (기본 열 순서 FEATURE_COLS)."""
    X = np.empty((len(rows), len(cols)), dtype=object)
    for i, r in enumerate(rows):
        for j, c in enumerate(cols):
            X[i, j] = r.get(c, 0)
    return X
