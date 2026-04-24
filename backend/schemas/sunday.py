from typing import List, Optional

from pydantic import BaseModel, Field


class SundayHistoryItem(BaseModel):
    """썬데이 이력 한 주. 활성 태그만 배열로."""

    date: str  # "2026.04.19"
    event: str  # "<메이플 어택!>" 또는 "(-)"
    active_tags: List[str]  # ["몬스터파크", "헥사_스텟"]


class SundayPredictionRankItem(BaseModel):
    """예측 1줄 (카테고리 단위 순위)."""

    rank: int
    probability: float = Field(..., description="0~1")
    probability_text: str
    event_name: str
    last_seen_days: Optional[int] = Field(None, description="target_date 이전 마지막 출현까지 일수")
    last_seen_text: str


class SundayPredictionBlock(BaseModel):
    """예측 한 건 (Supabase predictions 최신 1건 기준)."""

    target_date: Optional[str] = Field(None, description="예측 대상 일요일 YYYY-MM-DD")
    top_k: int
    predictions: List[SundayPredictionRankItem]


class SundayRecentWithPredictionResponse(BaseModel):
    """홈: JSON·스키마 순서 = 예측 블록 먼저, 최근 N주 이력 나중."""

    prediction: SundayPredictionBlock
    history: List[SundayHistoryItem]
