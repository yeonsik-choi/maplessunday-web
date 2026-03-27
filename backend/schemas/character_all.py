"""
GET /api/all 응답 스키마 — OpenAPI(/docs)용.

문서에 적힌 필드만 포함 (장비·심볼은 API 응답에서 허용 키만 통과).
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class EquipmentSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_items: int = 0
    items: list[dict[str, Any]] = Field(default_factory=list)


class UnionSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    union_level: int | str | None = None
    union_grade: str | None = None
    union_artifact_level: int | str | None = None
    union_raider_stats: Any = None
    union_occupied_stats: Any = None


class SymbolsSection(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    total: int = 0
    symbol_list: list[dict[str, Any]] = Field(
        default_factory=list,
        serialization_alias="list",
        validation_alias="list",
    )


CHARACTER_ALL_OPENAPI_EXAMPLE: dict[str, Any] = {
    "character_name": "캐릭터닉네임",
    "character_level": 280,
    "character_class": "나이트로드",
    "world_name": "루나",
    "character_image": "https://open.api.nexon.com/static/...",
    "character_guild_name": "길드명",
    "character_exp_rate": "50.973%",
    "date": "2025-03-20",
    "popularity": 42,
    "overall_rank": 150,
    "server_rank": 12,
    "class_rank": 3,
    "combat_power": "3575만 1234",
    "equipment": {
        "total_items": 1,
        "items": [
            {
                "item_equipment_slot": "모자",
                "item_name": "아케인셰이드 메이지햇",
                "item_icon": "https://...",
                "starforce": 22,
                "potential_option_grade": "레전드리",
                "potential_option_1": "STR +12%",
                "item_total_option": {},
                "item_base_option": {},
            }
        ],
    },
    "union": {
        "union_level": 8500,
        "union_grade": "마스터",
        "union_artifact_level": 10,
        "union_raider_stats": [],
        "union_occupied_stats": [],
    },
    "symbols": {
        "total": 1,
        "list": [
            {
                "symbol_name": "미궁",
                "symbol_icon": "https://...",
                "symbol_force": 60,
                "symbol_level": 20,
                "symbol_str": "100",
                "symbol_dex": "0",
                "symbol_int": "0",
                "symbol_luk": "0",
                "symbol_hp": "0",
                "symbol_growth_count": 0,
                "symbol_require_growth_count": 10,
            }
        ],
    },
}


class CharacterAllResponse(BaseModel):
    """캐릭터 정보창 통합 응답 (GET /api/all)."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"example": CHARACTER_ALL_OPENAPI_EXAMPLE},
    )

    character_image: str | None = None
    character_name: str | None = None
    world_name: str | None = None
    character_class: str | None = None
    character_guild_name: str | None = None
    character_level: int | str | None = None
    character_exp_rate: str | int | float | None = None
    date: str | None = None

    popularity: int | str | None = None
    combat_power: str | int | float | None = None

    overall_rank: int | None = None
    server_rank: int | None = None
    class_rank: int | None = None

    equipment: EquipmentSection = Field(default_factory=EquipmentSection)
    union: UnionSection = Field(default_factory=UnionSection)
    symbols: SymbolsSection = Field(default_factory=SymbolsSection)
