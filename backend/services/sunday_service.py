from typing import List

from constants.categories import CATEGORY_DISPLAY, CATEGORY_TAGS
from core.supabase_client import get_supabase
from schemas.sunday import CategoryInfo, SundayHistoryItem


def _tags_row_to_categories(row: dict) -> List[str]:
    """ssunday 한 행을 받아 활성 카테고리 배열 반환."""
    result = []
    for cat, tags in CATEGORY_TAGS.items():
        if any(int(row.get(t, 0)) == 1 for t in tags):
            result.append(cat)
    return result


def _format_row(row: dict) -> SundayHistoryItem:
    """Supabase 원본 행 → API 응답 포맷."""
    cats = _tags_row_to_categories(row)
    return SundayHistoryItem(
        date=row["date"],
        event=row.get("event", ""),
        categories=[
            CategoryInfo(key=c, display=CATEGORY_DISPLAY.get(c, c)) for c in cats
        ],
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
