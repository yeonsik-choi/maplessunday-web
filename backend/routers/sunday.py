from typing import List

from fastapi import APIRouter, Query

from schemas.sunday import SundayHistoryItem
from services import sunday_service

router = APIRouter(prefix="/api/sunday", tags=["sunday"])


@router.get(
    "/history/recent",
    response_model=List[SundayHistoryItem],
    summary="최근 N주 썬데이 이력",
    description="홈 페이지에서 사용. 기본 6주.",
)
def get_recent_history(
    limit: int = Query(6, ge=1, le=52, description="조회할 주 수"),
):
    return sunday_service.fetch_recent_history(limit=limit)


@router.get(
    "/history/all",
    response_model=List[SundayHistoryItem],
    summary="전체 썬데이 이력",
    description="캘린더 페이지에서 사용. 전체 이력 반환.",
)
def get_all_history():
    return sunday_service.fetch_all_history()
