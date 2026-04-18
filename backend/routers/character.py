import asyncio
import logging
import re
import unicodedata
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from core.config import NEXON_HTTP_TRUST_ENV
from schemas.character_all import (
    AbilityPresetUi,
    ArcaneRow,
    CharacterResponse,
    EquipTotalOptionUi,
    EquipUi,
    HexaMatrixStatUi,
    HexaStatCoreUi,
    HexaStatLineUi,
    JobSkillFifthBundle,
    JobSkillFifthCategorySectionUi,
    JobSkillSixthBundle,
    JobSkillSixthCategorySectionUi,
    JobSkillUi,
    LinkSkillPresetUi,
    SetEffectUi,
    UnionArtifactCrystalRow,
    UnionArtifactEffectRow,
    UnionArtifactSection,
    UnionChampionSection,
    UnionChampionSlotRow,
    UnionHeader,
    UnionPresetUi,
    UnionResponse,
)
from services.nexon_api import (
    fetch_character_ability,
    fetch_character_basic,
    fetch_character_hexamatrix,
    fetch_character_hexamatrix_stat,
    fetch_character_link_skill,
    fetch_character_popularity,
    fetch_character_skill,
    fetch_character_stat,
    fetch_character_vmatrix,
    fetch_item_equipment,
    fetch_overall_ranking,
    fetch_set_effect,
    fetch_union,
    fetch_union_artifact,
    fetch_union_champion,
    fetch_union_raider,
    get_ocid,
    get_yesterday,
    raise_nexon_request_error,
    require_nexon_api_key,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["캐릭터"])

_NEXON_TIMEOUT_SEC = 30.0
_NEXON_SLEEP_SEC = 1.0

_NEXON_FETCH_NAMES = (
    "basic",
    "stat",
    "ability",
    "item_equipment",
    "popularity",
    "union",
    "union_raider",
    "union_artifact",
    "union_champion",
    "ranking",
    "set_effect",
    "skill_grade_6",
    "skill_grade_5",
    "hexamatrix_stat",
    "hexamatrix",
    "vmatrix",
    "link_skill",
)

_EQUIP_SLOTS: tuple[str, ...] = (
    "무기",
    "보조무기",
    "엠블렘",
    "모자",
    "상의",
    "하의",
    "장갑",
    "신발",
    "망토",
    "어깨장식",
    "얼굴장식",
    "눈장식",
    "귀고리",
    "벨트",
    "펜던트",
    "펜던트2",
    "반지1",
    "반지2",
    "반지3",
    "반지4",
    "포켓 아이템",
    "기계 심장",
    "뱃지",
    "훈장",
)
_EQUIP_ORDER: dict[str, int] = {s: i for i, s in enumerate(_EQUIP_SLOTS)}

_ARCANE_NAMES = ("아케인포스", "아케인 포스")
_AUTH_NAMES = ("어센틱포스", "어센틱 포스")

_POTENTIAL_PAIRS = (
    ("potential_option_1", "potentialOption1"),
    ("potential_option_2", "potentialOption2"),
    ("potential_option_3", "potentialOption3"),
)
_ADDITIONAL_POTENTIAL_PAIRS = (
    ("additional_potential_option_1", "additionalPotentialOption1"),
    ("additional_potential_option_2", "additionalPotentialOption2"),
    ("additional_potential_option_3", "additionalPotentialOption3"),
)
_EQUIP_PRESET_KEYS = (
    ("item_equipment_preset_1", "itemEquipmentPreset1"),
    ("item_equipment_preset_2", "itemEquipmentPreset2"),
    ("item_equipment_preset_3", "itemEquipmentPreset3"),
)
_ABILITY_PRESET_KEYS = (
    ("ability_preset_1", "abilityPreset1"),
    ("ability_preset_2", "abilityPreset2"),
    ("ability_preset_3", "abilityPreset3"),
)
_UNION_CRYSTAL_OPTION_KEYS = (
    ("crystal_option_name_1", "crystalOptionName1"),
    ("crystal_option_name_2", "crystalOptionName2"),
    ("crystal_option_name_3", "crystalOptionName3"),
)
_INNER_STAT_SHORT = {
    "유니온 최대 HP": "HP",
    "유니온 DEX": "DEX",
    "유니온 STR": "STR",
    "유니온 INT": "INT",
    "유니온 LUK": "LUK",
    "유니온 최대 MP": "MP",
    "유니온 마력": "마력",
    "유니온 공격력": "공격력",
}


def _shorten_inner_stat_effect(text: str) -> str:
    if not text:
        return text
    s = text
    for long_k, short_v in sorted(
        _INNER_STAT_SHORT.items(), key=lambda kv: -len(kv[0])
    ):
        s = s.replace(long_k, short_v)
    return s


_CRYSTAL_NAME_PREFIX = re.compile(r"^크리스탈\s*:\s*")


def _crystal_display_name(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).strip()
    t = _CRYSTAL_NAME_PREFIX.sub("", s).strip()
    return t if t else s


def _nget(d: dict | None, *keys: str) -> Any:
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _nexon_str(d: dict | None, *keys: str) -> str | None:
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if v is None:
            continue
        t = str(v).strip()
        if t:
            return t
    return None


def _equip_slot(item: dict) -> str:
    v = _nget(item, "item_equipment_slot", "itemEquipmentSlot")
    return str(v).strip() if v is not None else ""


def _equip_rows(payload: dict) -> list:
    rows = _nget(payload, "item_equipment", "itemEquipment")
    return rows if isinstance(rows, list) else []


def _equip_rows_for_key(payload: dict, snake_key: str, camel_key: str) -> list:
    rows = _nget(payload, snake_key, camel_key)
    return rows if isinstance(rows, list) else []


def _preset_no_from_payload(payload: dict) -> int | None:
    v = _nget(payload, "preset_no", "presetNo")
    if v is None:
        return None
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    return _parse_int(v)


def _sorted_equips_from_rows(rows: list) -> list[EquipUi]:
    filtered = [
        row
        for row in rows
        if isinstance(row, dict) and _equip_slot(row) in _EQUIP_ORDER
    ]
    filtered.sort(key=lambda r: _EQUIP_ORDER[_equip_slot(r)])
    return [_to_equip(r) for r in filtered]


def _finalize_equipment_presets(
    preset_no: int | None,
    equipment_presets: list[list[EquipUi]],
    item_equipment: list[EquipUi],
) -> list[list[EquipUi]]:
    out = [list(p) for p in equipment_presets]
    while len(out) < 3:
        out.append([])
    out = out[:3]
    if item_equipment:
        if preset_no in (1, 2, 3):
            i = preset_no - 1
            if not out[i]:
                out[i] = list(item_equipment)
        elif not any(out):
            out[0] = list(item_equipment)
    return out


def _ability_preset_from_block(
    data: dict, snake_block: str, camel_block: str
) -> AbilityPresetUi:
    block = _nget(data, snake_block, camel_block)
    if not isinstance(block, dict):
        return AbilityPresetUi()
    gr = _nget(block, "ability_preset_grade", "abilityPresetGrade")
    grade = str(gr).strip() if gr is not None else None
    if grade == "":
        grade = None
    rows = _nget(block, "ability_info", "abilityInfo")
    if not isinstance(rows, list):
        rows = []
    lines: list[str] = []
    for i in range(3):
        if i < len(rows) and isinstance(rows[i], dict):
            av = _nget(rows[i], "ability_value", "abilityValue")
            lines.append(str(av) if av is not None else "")
        else:
            lines.append("")
    return AbilityPresetUi(grade=grade, lines=lines)


def _parse_int(raw) -> int | None:
    if raw is None:
        return None
    s = str(raw).replace(",", "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _equip_stat_int(v: Any) -> int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    return _parse_int(v)


def _final_stat_int(stat: dict, names: tuple[str, ...]) -> int | None:
    for row in stat.get("final_stat") or []:
        if isinstance(row, dict) and row.get("stat_name") in names:
            return _parse_int(row.get("stat_value"))
    return None


def _combat_power_raw(stat: dict) -> str | None:
    for row in stat.get("final_stat") or []:
        if isinstance(row, dict) and row.get("stat_name") == "전투력":
            return row.get("stat_value")
    return None


def _rank_int(payload: dict) -> int | None:
    rows = payload.get("ranking") or []
    if not rows or not isinstance(rows[0], dict):
        return None
    row = rows[0]
    raw = row.get("ranking") if row.get("ranking") is not None else row.get("rank")
    if raw is None:
        return None
    try:
        return int(str(raw).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


_UNION_BLOCK_COORD_KEYS = frozenset(
    (
        "block_control_point",
        "blockControlPoint",
        "block_position",
        "blockPosition",
    )
)


def _union_block_without_coords(block: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in block.items() if k not in _UNION_BLOCK_COORD_KEYS}


def _build_preset(preset_data: dict | None) -> UnionPresetUi:
    if not preset_data:
        return UnionPresetUi()
    blocks = _nget(preset_data, "union_block", "unionBlock")
    if not isinstance(blocks, list):
        blocks = []
    blocks_out: list[dict[str, Any]] = [
        _union_block_without_coords(dict(b)) for b in blocks if isinstance(b, dict)
    ]
    blocks_out.sort(
        key=lambda b: _parse_int(_nget(b, "block_level", "blockLevel")) or 0,
        reverse=True,
    )
    inner_raw = _nget(preset_data, "union_inner_stat", "unionInnerStat")
    inner_out: list[dict[str, Any]] = []
    if isinstance(inner_raw, list):
        for r in inner_raw:
            if not isinstance(r, dict):
                continue
            d = dict(r)
            for ek in ("stat_field_effect", "statFieldEffect"):
                if ek in d and isinstance(d[ek], str):
                    d[ek] = _shorten_inner_stat_effect(d[ek])
            inner_out.append(d)
    rs = _nget(preset_data, "union_raider_stat", "unionRaiderStat")
    raider_stats = [str(x) for x in rs] if isinstance(rs, list) else []
    occ = _nget(preset_data, "union_occupied_stat", "unionOccupiedStat")
    occupied = [str(x) for x in occ] if isinstance(occ, list) else []
    return UnionPresetUi(
        blocks=blocks_out,
        innerStats=inner_out,
        raiderStats=raider_stats,
        occupiedStats=occupied,
    )


def _build_union_artifact_section(artifact: dict) -> UnionArtifactSection:
    effects: list[UnionArtifactEffectRow] = []
    raw_eff = _nget(artifact, "union_artifact_effect", "unionArtifactEffect")
    if isinstance(raw_eff, list):
        for e in raw_eff:
            if not isinstance(e, dict):
                continue
            name = _nexon_str(e, "name") or ""
            lev = _parse_int(e.get("level"))
            effects.append(
                UnionArtifactEffectRow(name=name, level=lev if lev is not None else 0)
            )
    crystals: list[UnionArtifactCrystalRow] = []
    raw_cry = _nget(artifact, "union_artifact_crystal", "unionArtifactCrystal")
    if isinstance(raw_cry, list):
        for c in raw_cry:
            if not isinstance(c, dict):
                continue
            opts = [
                t
                for sk, ck in _UNION_CRYSTAL_OPTION_KEYS
                if (t := _nexon_str(c, sk, ck))
            ]
            crystals.append(
                UnionArtifactCrystalRow(
                    name=_crystal_display_name(_nexon_str(c, "name")),
                    level=_parse_int(c.get("level")),
                    validityFlag=_nexon_str(c, "validity_flag", "validityFlag"),
                    date_expire=_nexon_str(c, "date_expire", "dateExpire"),
                    options=opts,
                )
            )
    return UnionArtifactSection(effects=effects, crystals=crystals)


def _champion_badge_stat_lines(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    return [
        str(b["stat"])
        for b in raw
        if isinstance(b, dict) and b.get("stat") is not None
    ]


def _build_union_champion_section(champion: dict) -> UnionChampionSection:
    slots: list[UnionChampionSlotRow] = []
    raw_slots = _nget(champion, "union_champion", "unionChampion")
    if isinstance(raw_slots, list):
        for row in raw_slots:
            if not isinstance(row, dict):
                continue
            badges_raw = _nget(row, "champion_badge_info", "championBadgeInfo")
            slot_n = _parse_int(_nget(row, "champion_slot", "championSlot"))
            slots.append(
                UnionChampionSlotRow(
                    championName=_nexon_str(row, "champion_name", "championName"),
                    championSlot=slot_n,
                    championGrade=_nexon_str(row, "champion_grade", "championGrade"),
                    championClass=_nexon_str(row, "champion_class", "championClass"),
                    badgeEffects=_champion_badge_stat_lines(badges_raw),
                )
            )
    raw_total = _nget(champion, "champion_badge_total_info", "championBadgeTotalInfo")
    return UnionChampionSection(
        slots=slots,
        totalBadgeEffects=_champion_badge_stat_lines(raw_total),
    )


def _assemble_union_response(
    union_basic: dict,
    raider: dict,
    artifact: dict,
    champion: dict,
) -> UnionResponse:
    header = UnionHeader(
        grade=_nexon_str(union_basic, "union_grade", "unionGrade"),
        level=_parse_int(_nget(union_basic, "union_level", "unionLevel")),
        artifactLevel=_parse_int(
            _nget(union_basic, "union_artifact_level", "unionArtifactLevel")
        ),
    )
    active = _parse_int(_nget(raider, "use_preset_no", "usePresetNo"))
    presets: dict[str, UnionPresetUi] = {}
    for i in range(1, 6):
        pdata = _nget(raider, f"union_raider_preset_{i}", f"unionRaiderPreset{i}")
        presets[str(i)] = _build_preset(pdata if isinstance(pdata, dict) else None)

    return UnionResponse(
        header=header,
        champion=_build_union_champion_section(champion),
        artifact=_build_union_artifact_section(artifact),
        activePreset=active,
        presets=presets,
    )


def _coerce_level(raw) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    s = str(raw).replace(",", "").strip()
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None


def _fmt_thousands(n) -> str | None:
    if n is None:
        return None
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        t = str(n).strip()
        return t or None


def _fmt_combat_display(raw: str | None) -> str:
    if not raw:
        return ""
    s = str(raw).strip()
    if not s:
        return ""
    if "," in s:
        return s
    digits = re.sub(r"[^\d]", "", s)
    if not digits:
        return s
    try:
        return f"{int(digits):,}"
    except ValueError:
        return s


def _parse_exp_pct(raw) -> float | None:
    if raw is None:
        return None
    s = str(raw).strip().replace("%", "").replace(",", "")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_stars(raw) -> int:
    if raw is None:
        return 0
    s = str(raw).strip().replace(",", "")
    if not s:
        return 0
    m = re.match(r"^(\d+)", s)
    return min(int(m.group(1)), 30) if m else 0


def _grade_class(raw) -> str | None:
    if raw is None:
        return None
    exact = {
        "레어": "rare",
        "에픽": "epic",
        "유니크": "unique",
        "레전드리": "legendary",
        "rare": "rare",
        "epic": "epic",
        "unique": "unique",
        "legendary": "legendary",
    }
    return exact.get(str(raw).strip())


def _item_grade(item: dict) -> str | None:
    return _grade_class(_nget(item, "potential_option_grade", "potentialOptionGrade"))


def _item_additional_grade(item: dict) -> str | None:
    return _grade_class(
        _nget(item, "additional_potential_option_grade", "additionalPotentialOptionGrade")
    )


def _triple_option_lines(
    item: dict, pairs: tuple[tuple[str, str], ...]
) -> list[str]:
    out: list[str] = []
    for sk, ck in pairs:
        v = _nget(item, sk, ck)
        if v is None:
            continue
        t = str(v).strip()
        if t:
            out.append(t)
    return out


def _subdoc(item: dict, snake: str, camel: str) -> dict | None:
    v = _nget(item, snake, camel)
    return v if isinstance(v, dict) else None


def _snake_to_camel_key(key: str) -> str:
    if not key or not isinstance(key, str):
        return key
    if "_" not in key:
        return key
    parts = [p for p in key.split("_") if p != ""]
    if not parts:
        return key
    return parts[0].lower() + "".join(
        (p[:1].upper() + p[1:]) if p else "" for p in parts[1:]
    )


def _deep_camelize_keys(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            _snake_to_camel_key(k) if isinstance(k, str) else k: _deep_camelize_keys(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_deep_camelize_keys(x) for x in obj]
    return obj


def _scalar_to_json_number(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v) if v == int(v) else v
    if isinstance(v, str):
        t = v.strip().replace(",", "")
        if not t:
            return v
        try:
            if "." in t:
                f = float(t)
                return int(f) if f == int(f) else f
            return int(t)
        except (ValueError, OverflowError):
            return v
    return v


def _deep_coerce_equip_numbers(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _deep_coerce_equip_numbers(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_deep_coerce_equip_numbers(x) for x in obj]
    return _scalar_to_json_number(obj)


def _camel_equip_subdoc(item: dict, snake: str, camel: str) -> dict[str, Any] | None:
    d = _subdoc(item, snake, camel)
    if d is None:
        return None
    return _deep_coerce_equip_numbers(_deep_camelize_keys(d))


def _cuttable_count_ui(item: dict) -> int | None:
    v = _nget(item, "cuttable_count", "cuttableCount")
    if v is None:
        return None
    n = _equip_stat_int(v)
    if n is None or n == 255:
        return None
    return n


def _total_option_ui(item: dict) -> EquipTotalOptionUi | None:
    raw = _subdoc(item, "item_total_option", "itemTotalOption")
    if not raw:
        return None

    def gi(*keys: str) -> int | None:
        return _equip_stat_int(_nget(raw, *keys))

    ui = EquipTotalOptionUi(
        str_bonus=gi("str", "STR"),
        dex=gi("dex", "DEX"),
        int_bonus=gi("int", "INT"),
        luk=gi("luk", "LUK"),
        max_hp=gi("max_hp", "maxHp"),
        max_mp=gi("max_mp", "maxMp"),
        attack_power=gi("attack_power", "attackPower"),
        magic_power=gi("magic_power", "magicPower"),
        armor=gi("armor"),
        ignore_monster_armor=gi("ignore_monster_armor", "ignoreMonsterArmor"),
        all_stat=gi("all_stat", "allStat"),
        boss_damage=gi("boss_damage", "bossDamage"),
    )
    if not ui.model_dump(exclude_none=True):
        return None
    return ui


def _to_equip(item: dict) -> EquipUi:
    name = _nget(item, "item_name", "itemName")
    pots = _triple_option_lines(item, _POTENTIAL_PAIRS)
    add_pots = _triple_option_lines(item, _ADDITIONAL_POTENTIAL_PAIRS)
    base_block = _subdoc(item, "item_base_option", "itemBaseOption")
    total_opt = _total_option_ui(item)
    apots = add_pots if add_pots else None

    base_option_cam = (
        _deep_coerce_equip_numbers(_deep_camelize_keys(base_block))
        if base_block
        else None
    )

    return EquipUi(
        slot=_equip_slot(item) or None,
        name=name,
        stars=_parse_stars(item.get("starforce")),
        grade=_item_grade(item),
        potential=pots if pots else None,
        item_icon=_nexon_str(item, "item_icon", "itemIcon"),
        base_equipment_level=_equip_stat_int(
            _nexon_str(base_block, "base_equipment_level", "baseEquipmentLevel")
        ),
        scroll_upgrade=_parse_int(_nexon_str(item, "scroll_upgrade", "scrollUpgrade")),
        additional_grade=_item_additional_grade(item),
        additional_potential=apots,
        total_option=total_opt,
        base_option=base_option_cam,
        add_option=_camel_equip_subdoc(item, "item_add_option", "itemAddOption"),
        etc_option=_camel_equip_subdoc(item, "item_etc_option", "itemEtcOption"),
        starforce_option=_camel_equip_subdoc(
            item, "item_starforce_option", "itemStarforceOption"
        ),
        scroll_upgradeable_count=_parse_int(
            _nexon_str(item, "scroll_upgradeable_count", "scrollUpgradeableCount")
        ),
        cuttable_count=_cuttable_count_ui(item),
        soul_name=_nexon_str(item, "soul_name", "soulName"),
        soul_option=_nexon_str(item, "soul_option", "soulOption"),
    )


def _norm_skill_key(s: str) -> str:
    t = unicodedata.normalize("NFKC", (s or "").strip())
    return re.sub(r"\s+", " ", t).strip()


def _squish_display_text(s: str) -> str:
    t = unicodedata.normalize("NFKC", s or "")
    t = re.sub(r"[\t\r\f\v]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    t = re.sub(r"[ \u3000]+", " ", t)
    return t.strip()


def _absolute_icon_url(url: str) -> str:
    u = (url or "").strip()
    if not u:
        return ""
    if u.startswith("//"):
        return f"https:{u}"
    return u


def _slim_skill_api_row(row: dict) -> dict[str, Any]:
    name = _norm_skill_key(str(_nget(row, "skill_name", "skillName") or ""))
    desc = _squish_display_text(
        str(_nget(row, "skill_description", "skillDescription") or "")
    )
    effect = _squish_display_text(
        str(_nget(row, "skill_effect", "skillEffect") or "")
    )
    icon = _absolute_icon_url(str(_nget(row, "skill_icon", "skillIcon") or ""))
    lvl = _parse_int(_nget(row, "skill_level", "skillLevel")) or 0
    return {
        "skillName": name,
        "skillLevel": lvl,
        "skillIcon": icon,
        "skillDescription": desc,
        "skillEffect": effect,
    }


def _job_skill_ui_list_from_any(v: Any) -> list[JobSkillUi]:
    if v is None:
        return []
    rows: list[Any] = [v] if isinstance(v, dict) else (v if isinstance(v, list) else [])
    out: list[JobSkillUi] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        slim = _slim_skill_api_row(row)
        if not _norm_skill_key(str(slim.get("skillName") or "")):
            continue
        out.append(JobSkillUi.model_validate(slim))
    return out


def _link_skill_presets_ui(link_raw: dict) -> list[LinkSkillPresetUi]:
    presets: list[LinkSkillPresetUi] = []
    for i in (1, 2, 3):
        owned = _nget(
            link_raw,
            f"character_owned_link_skill_preset_{i}",
            f"characterOwnedLinkSkillPreset{i}",
        )
        skills = _nget(
            link_raw,
            f"character_link_skill_preset_{i}",
            f"characterLinkSkillPreset{i}",
        )
        presets.append(
            LinkSkillPresetUi(
                presetNo=i,
                ownedSkill=_job_skill_ui_list_from_any(owned),
                skills=_job_skill_ui_list_from_any(skills),
            )
        )
    return presets


def _hexa_stat_line(name_raw: Any, level_raw: Any) -> HexaStatLineUi | None:
    name = str(name_raw or "").strip()
    if not name:
        return None
    return HexaStatLineUi(level=_parse_int(level_raw) or 0, name=name)


def _hexa_stat_core_from_row(row: dict) -> HexaStatCoreUi:
    rows: list[HexaStatLineUi] = []
    for nm, lv in (
        (_nget(row, "main_stat_name", "mainStatName"), _nget(row, "main_stat_level", "mainStatLevel")),
        (
            _nget(row, "sub_stat_name_1", "subStatName1"),
            _nget(row, "sub_stat_level_1", "subStatLevel1"),
        ),
        (
            _nget(row, "sub_stat_name_2", "subStatName2"),
            _nget(row, "sub_stat_level_2", "subStatLevel2"),
        ),
    ):
        line = _hexa_stat_line(nm, lv)
        if line is not None:
            rows.append(line)
    return HexaStatCoreUi(rows=rows)


def _hexa_stat_core_list(raw: Any) -> list[HexaStatCoreUi]:
    if not isinstance(raw, list):
        return []
    out: list[HexaStatCoreUi] = []
    for r in raw:
        if isinstance(r, dict):
            out.append(_hexa_stat_core_from_row(r))
    return out


def _hexa_matrix_stat_ui(payload: dict) -> HexaMatrixStatUi:
    return HexaMatrixStatUi(
        characterHexaStatCore=_hexa_stat_core_list(
            _nget(payload, "character_hexa_stat_core", "characterHexaStatCore")
        ),
        characterHexaStatCore2=_hexa_stat_core_list(
            _nget(payload, "character_hexa_stat_core_2", "characterHexaStatCore2")
        ),
        characterHexaStatCore3=_hexa_stat_core_list(
            _nget(payload, "character_hexa_stat_core_3", "characterHexaStatCore3")
        ),
    )


def _skills_from_character_skill_payload(payload: dict) -> list[dict[str, Any]]:
    raw = _nget(payload, "character_skill", "characterSkill")
    if not isinstance(raw, list):
        return []
    out = [_slim_skill_api_row(r) for r in raw if isinstance(r, dict)]
    return [r for r in out if _norm_skill_key(str(r.get("skillName") or ""))]


def _job_skills_by_norm_key(skill_raw: dict) -> dict[str, JobSkillUi]:
    out: dict[str, JobSkillUi] = {}
    for slim in _skills_from_character_skill_payload(skill_raw):
        nk = _norm_skill_key(str(slim.get("skillName") or ""))
        if nk:
            out[nk] = JobSkillUi.model_validate(slim)
    return out


def _collapse_type_ws(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").strip())


def _slot_sort_key(row: dict) -> tuple[int, int | str]:
    sid_raw = _nget(row, "slot_id", "slotId")
    try:
        return (0, int(str(sid_raw).strip()))
    except (TypeError, ValueError):
        return (1, str(sid_raw or ""))


def _vmatrix_v_core_rows_sorted(vmatrix_raw: dict) -> list[dict]:
    raw = _nget(
        vmatrix_raw,
        "character_v_core_equipment",
        "characterVCoreEquipment",
    )
    if not isinstance(raw, list):
        return []
    return sorted([r for r in raw if isinstance(r, dict)], key=_slot_sort_key)


def _fifth_vmatrix_label_from_row_type(core_type: str) -> str:
    raw = (core_type or "").strip()
    if not raw:
        return "기타"
    t = _collapse_type_ws(raw)
    tl = raw.lower()
    if "특수" in raw or "special" in tl:
        return "특수 코어"
    if "공용" in raw or "common" in tl:
        return "공용 코어"
    if "강화" in t or "enhance" in tl or "boost" in tl:
        return "강화 코어"
    if "직업" in raw or "스킬" in t or "skill" in tl:
        return "직업 코어"
    return "기타"


def _fifth_vmatrix_category_maps(
    rows: list[dict],
) -> tuple[dict[str, str], list[tuple[str, str]]]:
    name_to_label: dict[str, str] = {}
    boost_bundles: list[tuple[str, str]] = []
    for row in rows:
        label = _fifth_vmatrix_label_from_row_type(
            str(_nget(row, "v_core_type", "vCoreType") or "")
        )
        if label == "강화 코어":
            vn = str(_nget(row, "v_core_name", "vCoreName") or "").strip()
            if vn:
                boost_bundles.append((vn, label))
        for sk in (
            _nget(row, "v_core_skill_1", "vCoreSkill1"),
            _nget(row, "v_core_skill_2", "vCoreSkill2"),
            _nget(row, "v_core_skill_3", "vCoreSkill3"),
            _nget(row, "v_core_name", "vCoreName"),
        ):
            if sk is None:
                continue
            t = str(sk).strip()
            if not t:
                continue
            nk = _norm_skill_key(t)
            if nk and nk not in name_to_label:
                name_to_label[nk] = label
    return name_to_label, boost_bundles


def _fifth_find_v_category(
    skill_name: str,
    name_to_label: dict[str, str],
    boost_bundles: list[tuple[str, str]],
) -> str:
    nk = _norm_skill_key(skill_name)
    if nk in name_to_label:
        return name_to_label[nk]
    raw = (skill_name or "").strip()
    if " 강화" in raw or raw.endswith("강화"):
        base = raw.replace(" 강화", "").strip()
        if base:
            for v_bundle, lab in boost_bundles:
                if base in v_bundle:
                    return lab
    return "기타"


def _hexa_linked_skill_specs(row: dict) -> list[tuple[str, str]]:
    raw = _nget(row, "linked_skill", "linkedSkill")
    if not isinstance(raw, list):
        return []
    out: list[tuple[str, str]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        hid = _nget(item, "hexa_skill_id", "hexaSkillId")
        if hid is None or not str(hid).strip():
            continue
        lid = str(hid).strip()
        hint = ""
        for hk in (
            "skill_name",
            "skillName",
            "hexa_skill_name",
            "hexaSkillName",
        ):
            v = _nget(item, hk)
            if v is not None and str(v).strip():
                hint = str(v).strip()
                break
        out.append((lid, hint))
    return out


def _is_hexa_stat_skill_name(skill_name: str) -> bool:
    n = (skill_name or "").strip()
    return "HEXA 스탯" in n or _norm_skill_key(n) == _norm_skill_key("HEXA 스탯")


def _sixth_linked_skill_ui(
    lid: str, hint: str, skill_by_name: dict[str, JobSkillUi]
) -> JobSkillUi | None:
    nk = _norm_skill_key(lid)
    if nk and nk in skill_by_name:
        return skill_by_name[nk]
    if hint:
        return skill_by_name.get(_norm_skill_key(hint))
    return None


def _sixth_hexa_core_section_sort_order(core_type: str) -> int:
    raw = (core_type or "").strip()
    if not raw:
        return 4
    t = _collapse_type_ws(raw)
    tl = raw.lower()
    if "마스터리" in raw or "mastery" in tl:
        return 0
    if "강화" in t or "enhance" in tl or "boost" in tl:
        return 1
    if "스킬" in t or "skill" in tl:
        return 2
    if "공용" in raw or "common" in tl:
        return 3
    return 4


def _job_skill_sixth_bundle(
    skill6_raw: dict, hexa_matrix_raw: dict
) -> JobSkillSixthBundle:
    skill_by_name = _job_skills_by_norm_key(skill6_raw)
    raw_eq = _nget(
        hexa_matrix_raw,
        "character_hexa_core_equipment",
        "characterHexaCoreEquipment",
    )
    rows_all = [r for r in raw_eq if isinstance(r, dict)] if isinstance(raw_eq, list) else []
    rows_sorted = sorted(rows_all, key=_slot_sort_key)
    buckets: dict[str, list[JobSkillUi]] = {}

    for row in rows_sorted:
        typ = str(_nget(row, "hexa_core_type", "hexaCoreType") or "").strip() or "기타"
        if typ not in buckets:
            buckets[typ] = []
        for lid, hint in _hexa_linked_skill_specs(row):
            sk = _sixth_linked_skill_ui(lid, hint, skill_by_name)
            if sk is None or _is_hexa_stat_skill_name(sk.skillName):
                continue
            buckets[typ].append(sk)

    section_types = sorted(
        buckets.keys(),
        key=lambda k: (_sixth_hexa_core_section_sort_order(k), k),
    )
    sections = [
        JobSkillSixthCategorySectionUi(hexaCoreType=t, skills=buckets[t])
        for t in section_types
    ]

    hexa_stat_ui: JobSkillUi | None = None
    for sk in skill_by_name.values():
        if _is_hexa_stat_skill_name(sk.skillName):
            hexa_stat_ui = sk
            break

    return JobSkillSixthBundle(sections=sections, hexaStatSkill=hexa_stat_ui)


def _job_skill_fifth_bundle(skill5_raw: dict, vmatrix_raw: dict) -> JobSkillFifthBundle:
    rows_sorted = _vmatrix_v_core_rows_sorted(vmatrix_raw)
    name_to_label, boost_bundles = _fifth_vmatrix_category_maps(rows_sorted)
    skill_by_name = _job_skills_by_norm_key(skill5_raw)
    buckets: dict[str, list[JobSkillUi]] = {}
    seen: set[str] = set()
    for row in rows_sorted:
        for sk in (
            _nget(row, "v_core_skill_1", "vCoreSkill1"),
            _nget(row, "v_core_skill_2", "vCoreSkill2"),
            _nget(row, "v_core_skill_3", "vCoreSkill3"),
        ):
            if sk is None:
                continue
            nm = str(sk).strip()
            if not nm:
                continue
            nk = _norm_skill_key(nm)
            ui = skill_by_name.get(nk)
            if ui is None or nk in seen:
                continue
            lab = _fifth_find_v_category(ui.skillName, name_to_label, boost_bundles)
            buckets.setdefault(lab, []).append(ui)
            seen.add(nk)
    for nk, ui in skill_by_name.items():
        if nk in seen:
            continue
        lab = _fifth_find_v_category(ui.skillName, name_to_label, boost_bundles)
        buckets.setdefault(lab, []).append(ui)
        seen.add(nk)
    order_labels = ("직업 코어", "강화 코어", "공용 코어", "특수 코어")
    sections = [
        JobSkillFifthCategorySectionUi(vCoreType=lab, skills=buckets.get(lab, []))
        for lab in order_labels
    ]
    if buckets.get("기타"):
        sections.append(
            JobSkillFifthCategorySectionUi(vCoreType="기타", skills=buckets["기타"])
        )
    return JobSkillFifthBundle(sections=sections)


def _set_effects_ui(payload: dict) -> list[SetEffectUi]:
    raw = _nget(payload, "set_effect", "setEffect")
    if not isinstance(raw, list):
        return []
    out: list[SetEffectUi] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        info = _nget(s, "set_effect_info", "setEffectInfo")
        if not isinstance(info, list) or not info:
            continue
        name = str(_nget(s, "set_name", "setName") or "")
        c = _parse_int(_nget(s, "total_set_count", "totalSetCount"))
        count = 0 if c is None else c
        effects: list[str] = []
        for row in info:
            if not isinstance(row, dict):
                continue
            opt = _nget(row, "set_option", "setOption")
            if opt is None:
                continue
            t = str(opt).strip()
            if t:
                effects.append(t)
        out.append(SetEffectUi(name=name, count=count, effects=effects))
    return out


@router.get(
    "/character",
    response_model=CharacterResponse,
    response_model_by_alias=True,
    responses={
        404: {"description": "해당 닉네임 캐릭터 없음"},
        429: {"description": "넥슨 API rate limit"},
        502: {"description": "넥슨 API HTTP 오류 또는 네트워크/프록시 연결 실패"},
    },
)
async def get_character_info(nickname: str):
    require_nexon_api_key()
    yesterday = get_yesterday()

    try:
        async with httpx.AsyncClient(
            timeout=_NEXON_TIMEOUT_SEC,
            trust_env=NEXON_HTTP_TRUST_ENV,
        ) as client:
            ocid = await get_ocid(client, nickname)
            batch1 = await asyncio.gather(
                fetch_character_basic(client, ocid, yesterday),
                fetch_character_stat(client, ocid, yesterday),
                fetch_character_ability(client, ocid, yesterday),
                return_exceptions=True,
            )
            await asyncio.sleep(_NEXON_SLEEP_SEC)
            batch2a = await asyncio.gather(
                fetch_item_equipment(client, ocid, yesterday),
                fetch_character_popularity(client, ocid, yesterday),
                fetch_union(client, ocid, yesterday),
                fetch_overall_ranking(client, ocid, yesterday),
                fetch_set_effect(client, ocid, yesterday),
                return_exceptions=True,
            )
            await asyncio.sleep(_NEXON_SLEEP_SEC)
            batch2b = await asyncio.gather(
                fetch_union_raider(client, ocid, yesterday),
                fetch_union_artifact(client, ocid, yesterday),
                fetch_union_champion(client, ocid, yesterday),
                return_exceptions=True,
            )
            await asyncio.sleep(_NEXON_SLEEP_SEC)
            batch3 = await asyncio.gather(
                fetch_character_skill(client, ocid, yesterday, "6"),
                fetch_character_skill(client, ocid, yesterday, "5"),
                fetch_character_hexamatrix_stat(client, ocid, yesterday),
                return_exceptions=True,
            )
            await asyncio.sleep(_NEXON_SLEEP_SEC)
            batch4 = await asyncio.gather(
                fetch_character_hexamatrix(client, ocid, yesterday),
                fetch_character_vmatrix(client, ocid, yesterday),
                fetch_character_link_skill(client, ocid, yesterday),
                return_exceptions=True,
            )
            results = list(batch1) + [
                *batch2a[:3],
                *batch2b,
                *batch2a[3:],
            ] + list(batch3) + list(batch4)
    except HTTPException:
        raise
    except httpx.RequestError as e:
        raise_nexon_request_error(e)

    for i, r in enumerate(results):
        if isinstance(r, Exception):
            name = (
                _NEXON_FETCH_NAMES[i]
                if i < len(_NEXON_FETCH_NAMES)
                else str(i)
            )
            if isinstance(r, HTTPException):
                logger.warning(
                    "nexon fetch failed %s: HTTP %s %s",
                    name,
                    r.status_code,
                    r.detail,
                )
            else:
                logger.warning("nexon fetch failed %s: %s", name, r)

    def pick(i: int) -> dict:
        r = results[i]
        return r if not isinstance(r, Exception) else {}

    basic = pick(0)
    stat = pick(1)
    ability_data = pick(2)
    equip_data = pick(3)
    pop_data = pick(4)
    union_data = pick(5)
    raider_data = pick(6)
    artifact_data = pick(7)
    champion_data = pick(8)
    rank_data = pick(9)
    set_effect_data = pick(10)
    skill6_raw = pick(11)
    skill5_raw = pick(12)
    hexa_raw = pick(13)
    hexa_matrix_raw = pick(14)
    vmatrix_raw = pick(15)
    link_skill_raw = pick(16)
    job_sixth = _job_skill_sixth_bundle(skill6_raw, hexa_matrix_raw)
    job_fifth = _job_skill_fifth_bundle(skill5_raw, vmatrix_raw)
    link_skill_presets = _link_skill_presets_ui(link_skill_raw)
    hexa_matrix_stat = _hexa_matrix_stat_ui(hexa_raw)

    item_equipment_equips = _sorted_equips_from_rows(_equip_rows(equip_data))
    preset_equip_lists = [
        _sorted_equips_from_rows(_equip_rows_for_key(equip_data, sk, ck))
        for sk, ck in _EQUIP_PRESET_KEYS
    ]
    equipment_preset_no = _preset_no_from_payload(equip_data)
    equipment_presets = _finalize_equipment_presets(
        equipment_preset_no,
        preset_equip_lists,
        item_equipment_equips,
    )

    ap1, ap2, ap3 = tuple(
        _ability_preset_from_block(ability_data, s, c)
        for s, c in _ABILITY_PRESET_KEYS
    )
    ability_preset_no = _preset_no_from_payload(ability_data)
    set_effects = _set_effects_ui(set_effect_data)

    af = _final_stat_int(stat, _ARCANE_NAMES)
    tf = _final_stat_int(stat, _AUTH_NAMES)

    arcane: list[ArcaneRow] = []
    if af is not None:
        arcane.append(ArcaneRow(k="아케인포스", v=f"{af:,}"))
    if tf is not None:
        arcane.append(ArcaneRow(k="어센틱포스", v=f"{tf:,}"))

    combat = _combat_power_raw(stat)
    disp = _fmt_combat_display(combat) if combat else ""

    rank_n = _rank_int(rank_data)
    pop_n = pop_data.get("popularity")
    union_n = _nget(union_data, "union_level", "unionLevel")
    union_level_str = _fmt_thousands(union_n) if union_n is not None else None

    union_detail = _assemble_union_response(
        union_data, raider_data, artifact_data, champion_data
    )

    ep0, ep1, ep2 = equipment_presets[0], equipment_presets[1], equipment_presets[2]

    return CharacterResponse(
        imageUrl=basic.get("character_image"),
        name=basic.get("character_name"),
        level=_coerce_level(basic.get("character_level")),
        world=basic.get("world_name"),
        job=basic.get("character_class"),
        ranking=_fmt_thousands(rank_n),
        popularity=_fmt_thousands(pop_n) if pop_n is not None else None,
        unionLevel=union_level_str,
        guild=basic.get("character_guild_name") or "",
        expPercent=_parse_exp_pct(basic.get("character_exp_rate")),
        combatPower=disp or None,
        arcane=arcane,
        abilityPresetNo=ability_preset_no,
        abilityPreset1=ap1,
        abilityPreset2=ap2,
        abilityPreset3=ap3,
        setEffects=set_effects,
        equipmentPresetNo=equipment_preset_no,
        equipsPreset1=ep0,
        equipsPreset2=ep1,
        equipsPreset3=ep2,
        hexaMatrixStat=hexa_matrix_stat,
        jobSkillSixth=job_sixth,
        jobSkillFifth=job_fifth,
        linkSkillPresets=link_skill_presets,
        union=union_detail,
    )
