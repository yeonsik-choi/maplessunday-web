from typing import List

from pydantic import BaseModel


class SundayHistoryItem(BaseModel):
    """썬데이 이력 한 주. 활성 태그만 배열로."""

    date: str  # "2026.04.19"
    event: str  # "<메이플 어택!>" 또는 "(-)"
    active_tags: List[str]  # ["몬스터파크", "헥사_스텟"]
