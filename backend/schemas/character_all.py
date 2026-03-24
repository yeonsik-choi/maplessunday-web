"""
GET /api/all 응답 스키마 — OpenAPI(/docs)용. 넥슨 원본 일부는 구조가 자주 바뀌므로 Any로 둔 필드가 있음.

정보창에서 쓰는 항목 ↔ JSON 필드 (통합 응답 기준):
  캐릭터 이미지  → character_image
  닉네임         → character_name
  서버           → world_name
  직업           → character_class
  길드           → character_guild_name
  랭킹           → overall_rank (없으면 null) / 날짜는 ranking_date
  인기도         → popularity / 날짜는 popularity_date
  레벨           → character_level
  유니온         → union (union_level, union_grade, …)
  전투력         → combat_power
  장비           → equipment.items (슬롯·이름·아이콘·잠재 등)
  심볼           → symbols.list (배열, 키 이름은 리터럴 "list")
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class MainStatItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = None
    value: str | int | float | None = None


class EquipmentItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot: str | None = None
    name: str | None = None
    icon: str | None = None
    starforce: int | str | None = None
    potential_option_grade: str | None = None
    potential_option_1: str | None = None
    potential_option_2: str | None = None
    potential_option_3: str | None = None
    additional_potential_option_grade: str | None = None
    additional_potential_option_1: str | None = None
    additional_potential_option_2: str | None = None
    additional_potential_option_3: str | None = None
    scroll_upgrade: int | str | None = None


class EquipmentSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    total_items: int = 0
    items: list[EquipmentItem] = Field(default_factory=list)


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
    """JSON 키 list는 Python 예약과 겹쳐 model_serializer로 맞춤."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    total: int = 0
    # 클라이언트/문서상 필드명은 "list"
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


# OpenAPI(/docs) "Example Value"용 — 실제 넥슨 필드와 다를 수 있으나 구조 파악용
CHARACTER_ALL_OPENAPI_EXAMPLE: dict[str, Any] = {
    "character_name": "캐릭터닉네임",
    "character_level": 280,
    "character_class": "나이트로드",
    "world_name": "루나",
    "character_image": "https://open.api.nexon.com/static/...",
    "character_gender": "male",
    "character_guild_name": "길드명",
    "date": "2025-03-20",
    "popularity": 42,
    "popularity_date": "2025-03-20",
    "overall_rank": 150,
    "ranking_date": "2025-03-20",
    "combat_power": "3575만 1234",
    "main_stats": [
        {"name": "STR", "value": "12345"},
        {"name": "DEX", "value": "12000"},
    ],
    "equipment": {
        "total_items": 15,
        "items": [
            {
                "slot": "모자",
                "name": "아케인셰이드 메이지햇",
                "icon": "https://...",
                "starforce": 22,
                "potential_option_grade": "레전드리",
                "potential_option_1": "STR +12%",
                "potential_option_2": None,
                "potential_option_3": None,
                "additional_potential_option_grade": None,
                "additional_potential_option_1": None,
                "additional_potential_option_2": None,
                "additional_potential_option_3": None,
                "scroll_upgrade": 10,
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
                "name": "미궁",
                "icon": "https://...",
                "force": 60,
                "level": 20,
                "str": "100",
                "dex": "0",
                "int": "0",
                "luk": "0",
                "hp": "0",
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
    """캐릭터 정보창 통합 응답 (GET /api/all). 필드↔UI 항목은 모듈 독스트링 표 참고."""

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
    date: str | None = None

    popularity: int | str | None = None
    popularity_date: str | None = None
    overall_rank: int | None = None
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
