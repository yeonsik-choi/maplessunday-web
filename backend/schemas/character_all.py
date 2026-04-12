from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

EquipGrade = Literal["rare", "epic", "unique", "legendary"]

_MODEL = ConfigDict(extra="ignore", populate_by_name=True)


class ArcaneRow(BaseModel):
    model_config = _MODEL

    k: str
    v: str


class EquipTotalOptionUi(BaseModel):
    model_config = _MODEL

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
    model_config = _MODEL

    grade: str | None = None
    lines: list[str] = Field(default_factory=list)


class SetEffectUi(BaseModel):
    model_config = _MODEL

    name: str
    count: int
    effects: list[str] = Field(default_factory=list)


class EquipUi(BaseModel):
    model_config = _MODEL

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
    cuttable_count: int | None = Field(default=None, serialization_alias="cuttableCount")
    soul_name: str | None = Field(default=None, serialization_alias="soulName")
    soul_option: str | None = Field(default=None, serialization_alias="soulOption")


class UnionPresetUi(BaseModel):
    model_config = _MODEL

    blocks: list[dict[str, Any]] = Field(default_factory=list)
    raiderStats: list[str] = Field(default_factory=list)
    occupiedStats: list[str] = Field(default_factory=list)
    innerStats: list[dict[str, Any]] = Field(default_factory=list)


class UnionHeader(BaseModel):
    model_config = _MODEL

    grade: str | None = None
    level: int | None = None
    artifactLevel: int | None = None


class UnionChampionSlotRow(BaseModel):
    model_config = _MODEL

    championName: str | None = Field(
        default=None,
        validation_alias=AliasChoices("champion_name", "championName"),
    )
    championSlot: int | None = Field(
        default=None,
        validation_alias=AliasChoices("champion_slot", "championSlot"),
    )
    championGrade: str | None = Field(
        default=None,
        validation_alias=AliasChoices("champion_grade", "championGrade"),
    )
    championClass: str | None = Field(
        default=None,
        validation_alias=AliasChoices("champion_class", "championClass"),
    )
    badgeEffects: list[str] = Field(default_factory=list)


class UnionChampionSection(BaseModel):
    model_config = _MODEL

    slots: list[UnionChampionSlotRow] = Field(default_factory=list)
    totalBadgeEffects: list[str] = Field(default_factory=list)


class UnionArtifactEffectRow(BaseModel):
    model_config = _MODEL

    name: str
    level: int


class UnionArtifactCrystalRow(BaseModel):
    model_config = _MODEL

    name: str
    level: int | None = None
    validityFlag: str | None = Field(
        default=None,
        validation_alias=AliasChoices("validity_flag", "validityFlag"),
    )
    date_expire: str | None = Field(
        default=None,
        validation_alias=AliasChoices("date_expire", "dateExpire"),
    )
    options: list[str] = Field(default_factory=list)


class UnionArtifactSection(BaseModel):
    model_config = _MODEL

    effects: list[UnionArtifactEffectRow] = Field(default_factory=list)
    crystals: list[UnionArtifactCrystalRow] = Field(default_factory=list)


class UnionResponse(BaseModel):
    model_config = _MODEL

    header: UnionHeader = Field(default_factory=UnionHeader)
    champion: UnionChampionSection = Field(default_factory=UnionChampionSection)
    artifact: UnionArtifactSection = Field(default_factory=UnionArtifactSection)
    activePreset: int | None = None
    presets: dict[str, UnionPresetUi] = Field(default_factory=dict)


class CharacterResponse(BaseModel):
    model_config = _MODEL

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

    abilityPresetNo: int | None = None
    abilityPreset1: AbilityPresetUi = Field(default_factory=AbilityPresetUi)
    abilityPreset2: AbilityPresetUi = Field(default_factory=AbilityPresetUi)
    abilityPreset3: AbilityPresetUi = Field(default_factory=AbilityPresetUi)

    setEffects: list[SetEffectUi] = Field(default_factory=list)

    equipmentPresetNo: int | None = None
    equipsPreset1: list[EquipUi] = Field(default_factory=list)
    equipsPreset2: list[EquipUi] = Field(default_factory=list)
    equipsPreset3: list[EquipUi] = Field(default_factory=list)

    union: UnionResponse | None = None
