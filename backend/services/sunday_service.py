from datetime import datetime
from typing import List, Optional

from constants.categories import TAG_COLUMNS
from constants.sunday_prediction import CATEGORY_EVENT_NAME, CATEGORY_TAGS
from core.supabase_client import get_supabase
from schemas.sunday import (
    SundayHistoryItem,
    SundayPredictionRankItem,
    SundayRecentWithPredictionResponse,
)


def _parse_ssunday_date(date_str: str) -> Optional[datetime]:
    for fmt in ("%Y.%m.%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str.strip(), fmt)
        except ValueError:
            continue
    return None


def _parse_target_date(date_str: str) -> Optional[datetime]:
    try:
        return datetime.strptime(date_str.strip()[:10], "%Y-%m-%d")
    except ValueError:
        return None


def _category_seen_in_row(row: dict, category: str) -> bool:
    for col in CATEGORY_TAGS.get(category, []):
        if int(row.get(col, 0)) == 1:
            return True
    return False


def _last_seen_days_before(
    ssunday_rows: List[dict],
    category: str,
    target_dt: datetime,
) -> Optional[int]:
    """target_dt(예측 일요일) **이전** 주차 중, 해당 카테고리가 마지막으로 잡힌 날까지의 일수."""
    best: Optional[datetime] = None
    for row in ssunday_rows:
        ds = row.get("date")
        if not ds:
            continue
        d = _parse_ssunday_date(str(ds))
        if d is None or d >= target_dt:
            continue
        if _category_seen_in_row(row, category):
            if best is None or d > best:
                best = d
    if best is None:
        return None
    delta = target_dt.date() - best.date()
    return int(delta.days)


def _format_row(row: dict) -> SundayHistoryItem:
    """Supabase 원본 행 → API 응답. 값이 1인 태그만 배열로."""
    active = [col for col in TAG_COLUMNS if int(row.get(col, 0)) == 1]
    return SundayHistoryItem(
        date=row["date"],
        event=row.get("event", ""),
        active_tags=active,
    )


def fetch_recent_history(limit: int = 6) -> List[SundayHistoryItem]:
    """홈 페이지용: 최근 N주 이력."""
    sb = get_supabase()
    res = (
        sb.table("ssunday")
        .select("*")
        .order("date", desc=True)
        .limit(limit)
        .execute()
    )
    return [_format_row(row) for row in res.data]


def fetch_recent_with_prediction(
    *,
    history_limit: int = 6,
    prediction_top_k: int = 5,
) -> SundayRecentWithPredictionResponse:
    """홈: 최신 predictions 상위 K + 최근 N주 ssunday."""
    sb = get_supabase()
    k = max(1, min(prediction_top_k, 9))

    pred_rows = (
        sb.table("predictions")
        .select("target_date, probs")
        .order("target_date", desc=True)
        .limit(1)
        .execute()
    )
    target_date: Optional[str] = None
    ranked: List[tuple[str, float]] = []
    if pred_rows.data:
        raw = pred_rows.data[0]
        target_date = str(raw.get("target_date", ""))[:10] or None
        probs = raw.get("probs") or {}
        if isinstance(probs, dict):
            for cat, p in probs.items():
                try:
                    ranked.append((str(cat), float(p)))
                except (TypeError, ValueError):
                    continue
            ranked.sort(key=lambda x: -x[1])

    ss_res = (
        sb.table("ssunday")
        .select("*")
        .order("date", desc=True)
        .limit(400)
        .execute()
    )
    ss_rows: List[dict] = list(ss_res.data or [])
    history = [_format_row(r) for r in ss_rows[:history_limit]]
    target_dt = _parse_target_date(target_date) if target_date else None

    predictions: List[SundayPredictionRankItem] = []
    for i, (cat, p) in enumerate(ranked[:k], start=1):
        last_days = (
            _last_seen_days_before(ss_rows, cat, target_dt)
            if target_dt is not None
            else None
        )
        if last_days is None:
            last_txt = "유사 출현 없음"
        else:
            last_txt = f"{last_days}일 경과"
        predictions.append(
            SundayPredictionRankItem(
                rank=i,
                probability=round(p, 4),
                probability_text=f"{p * 100:.1f}%",
                event_name=CATEGORY_EVENT_NAME.get(cat, cat),
                last_seen_days=last_days,
                last_seen_text=last_txt,
            )
        )

    return SundayRecentWithPredictionResponse(
        target_date=target_date,
        top_k=k,
        predictions=predictions,
        history=history,
    )


def fetch_all_history() -> List[SundayHistoryItem]:
    """캘린더 페이지용: 전체 이력."""
    sb = get_supabase()
    res = (
        sb.table("ssunday").select("*").order("date", desc=True).execute()
    )
    return [_format_row(row) for row in res.data]
