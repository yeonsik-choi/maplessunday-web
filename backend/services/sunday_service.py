from typing import List

from constants.categories import TAG_COLUMNS
from core.supabase_client import get_supabase
from schemas.sunday import SundayHistoryItem


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


def fetch_all_history() -> List[SundayHistoryItem]:
    """캘린더 페이지용: 전체 이력."""
    sb = get_supabase()
    res = (
        sb.table("ssunday").select("*").order("date", desc=True).execute()
    )
    return [_format_row(row) for row in res.data]
