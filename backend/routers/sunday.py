from typing import List

from fastapi import APIRouter, Query

from schemas.sunday import SundayHistoryItem, SundayRecentWithPredictionResponse
from services import sunday_service

router = APIRouter(prefix="/api/sunday", tags=["sunday"])


@router.get(
    "/history/recent",
    response_model=SundayRecentWithPredictionResponse,
    summary="최근 N주 썬데이 이력 + 최신 예측",
    description="홈 페이지. 응답 순서: prediction(최신 1건 상위 K) → history(ssunday 최근 N주).",
)
def get_recent_history(
    limit: int = Query(6, ge=1, le=52, description="조회할 주 수 (ssunday)"),
    prediction_top_k: int = Query(
        5, ge=1, le=9, description="예측 카테고리 상위 개수 (probs 기준)"
    ),
):
    return sunday_service.fetch_recent_with_prediction(
        history_limit=limit,
        prediction_top_k=prediction_top_k,
    )


@router.get(
    "/history/all",
    response_model=List[SundayHistoryItem],
    summary="전체 썬데이 이력",
    description="캘린더 페이지에서 사용. 전체 이력 반환.",
)
def get_all_history():
    return sunday_service.fetch_all_history()
