from typing import List

from pydantic import BaseModel


class CategoryInfo(BaseModel):
    """카테고리 한 개."""

    key: str  # "사냥"
    display: str  # "🏹 사냥 (...)"


class SundayHistoryItem(BaseModel):
    """썬데이 이력 한 주."""

    date: str  # "2026.04.19"
    event: str  # "<메이플 어택!>" 또는 "(-)"
    categories: List[CategoryInfo]  # 활성 카테고리
