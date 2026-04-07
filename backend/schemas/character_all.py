from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

EquipGrade = Literal["rare", "epic", "unique", "legendary"]


class ArcaneRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    k: str
    v: str


class EquipTotalOptionUi(BaseModel):
    """item_total_option — 스탯 수치(정수)."""

    model_config = ConfigDict(extra="ignore")

    str_bonus: int | None = Field(default=None, serialization_alias="str")
    dex: int | None = None
    int_bonus: int | None = Field(default=None, serialization_alias="int")
    luk: int | None = None
    max_hp: int | None = Field(default=None, serialization_alias="maxHp")
    max_mp: int | None = Field(default=None, serialization_alias="maxMp")
    attack_power: int | None = Field(default=None, serialization_alias="attackPower")
    magic_power: int | None = Field(default=None, serialization_alias="magicPower")
    armor: int | None = None
    ignore_monster_armor: int | None = Field(
        default=None, serialization_alias="ignoreMonsterArmor"
    )
    all_stat: int | None = Field(default=None, serialization_alias="allStat")
    boss_damage: int | None = Field(default=None, serialization_alias="bossDamage")


class AbilityPresetUi(BaseModel):
    """명성 어빌리티 저장 프리셋 1건 (등급 + 3줄 텍스트)."""

    model_config = ConfigDict(extra="ignore")

    grade: str | None = None
    lines: list[str] = Field(default_factory=list)


class EquipUi(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot: str | None = None
    name: str | None = None
    stars: int = 0
    grade: EquipGrade | None = Field(
        default=None,
        description="메인 잠재 등급 → rare|epic|unique|legendary, 없으면 null",
    )
    potential: list[str] | None = None

    item_icon: str | None = Field(default=None, serialization_alias="itemIcon")
    base_equipment_level: int | None = Field(
        default=None, serialization_alias="baseEquipmentLevel"
    )
    scroll_upgrade: int | None = Field(default=None, serialization_alias="scrollUpgrade")
    additional_grade: EquipGrade | None = Field(
        default=None, serialization_alias="additionalGrade"
    )
    additional_potential: list[str] | None = Field(
        default=None, serialization_alias="additionalPotential"
    )

    total_option: EquipTotalOptionUi | None = Field(
        default=None, serialization_alias="totalOption"
    )
    base_option: dict[str, Any] | None = Field(
        default=None, serialization_alias="baseOption"
    )
    add_option: dict[str, Any] | None = Field(
        default=None, serialization_alias="addOption"
    )
    etc_option: dict[str, Any] | None = Field(
        default=None, serialization_alias="etcOption"
    )
    starforce_option: dict[str, Any] | None = Field(
        default=None, serialization_alias="starforceOption"
    )

    scroll_upgradeable_count: int | None = Field(
        default=None, serialization_alias="scrollUpgradeableCount"
    )
    scroll_resilience_count: int | None = Field(
        default=None, serialization_alias="scrollResilienceCount"
    )
    cuttable_count: int | None = Field(default=None, serialization_alias="cuttableCount")
    soul_name: str | None = Field(default=None, serialization_alias="soulName")
    soul_option: str | None = Field(default=None, serialization_alias="soulOption")
    shape_name: str | None = Field(default=None, serialization_alias="shapeName")
    has_moru: bool = Field(default=False, serialization_alias="hasMoru")


class CharacterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    imageUrl: str | None = None
    name: str | None = None
    level: int | None = None
    world: str | None = None
    job: str | None = None
    ranking: str | None = None
    popularity: str | None = None
    unionLevel: str | None = None
    guild: str | None = None
    expPercent: float | None = None
    combatPower: str | None = None
    arcane: list[ArcaneRow] = Field(default_factory=list)
    abilities: list[str] = Field(default_factory=list)
    equips: list[EquipUi] = Field(default_factory=list)

    equipmentPresetNo: int | None = Field(
        default=None,
        description="넥슨 item-equipment 응답의 preset_no (현재 선택 장비 프리셋)",
    )
    equipsPreset1: list[EquipUi] = Field(default_factory=list)
    equipsPreset2: list[EquipUi] = Field(default_factory=list)
    equipsPreset3: list[EquipUi] = Field(default_factory=list)

    abilityPresetNo: int | None = Field(
        default=None,
        description="넥슨 ability 응답의 preset_no (현재 선택 어빌 프리셋)",
    )
    abilityPreset1: AbilityPresetUi = Field(default_factory=AbilityPresetUi)
    abilityPreset2: AbilityPresetUi = Field(default_factory=AbilityPresetUi)
    abilityPreset3: AbilityPresetUi = Field(default_factory=AbilityPresetUi)
