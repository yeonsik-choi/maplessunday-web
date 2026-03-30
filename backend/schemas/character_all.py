from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EquipGrade = Literal["rare", "epic", "unique", "legendary"]


class ArcaneRow(BaseModel):
    model_config = ConfigDict(extra="ignore")
    k: str
    v: str


class EquipUi(BaseModel):
    model_config = ConfigDict(extra="ignore")

    slot: str | None = None
    name: str | None = None
    stars: int = 0
    grade: EquipGrade | None = Field(
        default=None,
        description="잠재 등급 → rare|epic|unique|legendary, 없으면 null",
    )
    potential: list[str] | None = None


class UnionUi(BaseModel):
    model_config = ConfigDict(extra="ignore")

    level: str | None = None


class CharacterResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    imageUrl: str | None = None
    name: str | None = None
    level: int | None = None
    world: str | None = None
    job: str | None = None
    ranking: str | None = None
    popularity: str | None = None
    union: UnionUi = Field(default_factory=UnionUi)
    unionLevel: str | None = None
    guild: str | None = None
    expPercent: float | None = None
    combatPower: str | None = None
    arcaneForce: str | None = None
    authenticForce: str | None = None
    arcane: list[ArcaneRow] = Field(default_factory=list)
    abilities: list[str] = Field(default_factory=list)
    equips: list[EquipUi] = Field(default_factory=list)
