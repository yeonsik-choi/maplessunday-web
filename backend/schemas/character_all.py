"""
GET /api/all 응답 스키마 — OpenAPI(/docs)용.

정보창 항목 ↔ JSON (통합 응답):
  캐릭터 이미지  → character_image
  닉네임         → character_name
  서버           → world_name
  직업           → character_class
  길드           → character_guild_name
  레벨           → character_level
  경험치%        → character_exp_rate
  랭킹           → overall_rank / server_rank / class_rank (null 가능), ranking_date
  인기도         → popularity / popularity_date
  전투력·스탯    → combat_power, main_stats
  장비           → equipment.items (넥슨 item-equipment 원본 키 그대로)
  유니온         → union
  심볼           → symbols.list (넥슨 symbol_* 키 그대로, JSON 키 이름은 "list")
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MainStatItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    value: str | int | float | None = None


class EquipmentSection(BaseModel):
    """items: 넥슨 character/item-equipment 의 각 장비 객체(원본 필드명)."""

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


class HyperStatSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    use_preset_no: int | str | None = None
    preset_1: Any = None
    preset_2: Any = None
    preset_3: Any = None


class SymbolsSection(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    total: int = 0
    symbol_list: list[dict[str, Any]] = Field(
        default_factory=list,
        serialization_alias="list",
        validation_alias="list",
    )


class AbilitySection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    grade: str | None = None
    info: Any = None
    preset_1: Any = None
    preset_2: Any = None
    preset_3: Any = None


CHARACTER_ALL_OPENAPI_EXAMPLE: dict[str, Any] = {
    "character_name": "캐릭터닉네임",
    "character_level": 280,
    "character_class": "나이트로드",
    "world_name": "루나",
    "character_image": "https://open.api.nexon.com/static/...",
    "character_gender": "male",
    "character_guild_name": "길드명",
    "character_exp_rate": "50.973%",
    "date": "2025-03-20",
    "popularity": 42,
    "popularity_date": "2025-03-20",
    "overall_rank": 150,
    "server_rank": 12,
    "class_rank": 3,
    "ranking_date": "2025-03-20",
    "combat_power": "3575만 1234",
    "main_stats": [
        {"name": "STR", "value": "12345"},
        {"name": "DEX", "value": "12000"},
    ],
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
    "hyper_stat": {
        "use_preset_no": 1,
        "preset_1": [],
        "preset_2": [],
        "preset_3": [],
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
    "ability": {
        "grade": "레전드리",
        "info": [],
        "preset_1": [],
        "preset_2": [],
        "preset_3": [],
    },
    "set_effect": [],
    "link_skill": [],
    "hexamatrix": [],
    "hexamatrix_stat": [],
}


class CharacterAllResponse(BaseModel):
    """캐릭터 정보창 통합 응답 (GET /api/all)."""

    model_config = ConfigDict(
        extra="ignore",
        json_schema_extra={"example": CHARACTER_ALL_OPENAPI_EXAMPLE},
    )

    character_name: str | None = None
    character_level: int | str | None = None
    character_class: str | None = None
    world_name: str | None = None
    character_image: str | None = None
    character_gender: str | None = None
    character_guild_name: str | None = None
    character_exp_rate: str | int | float | None = None
    date: str | None = None

    popularity: int | str | None = None
    popularity_date: str | None = None
    overall_rank: int | None = None
    server_rank: int | None = None
    class_rank: int | None = None
    ranking_date: str | None = None

    combat_power: str | int | float | None = None
    main_stats: list[MainStatItem] = Field(default_factory=list)

    equipment: EquipmentSection = Field(default_factory=EquipmentSection)
    union: UnionSection = Field(default_factory=UnionSection)
    hyper_stat: HyperStatSection = Field(default_factory=HyperStatSection)
    symbols: SymbolsSection = Field(default_factory=SymbolsSection)
    ability: AbilitySection = Field(default_factory=AbilitySection)

    set_effect: Any = None
    link_skill: Any = None
    hexamatrix: Any = None
    hexamatrix_stat: Any = None
