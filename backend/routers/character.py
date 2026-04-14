import asyncio
import logging
import re
import unicodedata
from typing import Any, Literal, cast

import httpx
from fastapi import APIRouter, HTTPException

from core.config import NEXON_API_KEY, NEXON_HTTP_TRUST_ENV
from schemas.character_all import (
    AbilityPresetUi,
    ArcaneRow,
    CharacterResponse,
    EquipTotalOptionUi,
    EquipUi,
    HexaStatColumnUi,
    HexaStatLineUi,
    HexaStatSlotUi,
    JobSkillUi,
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
    fetch_character_hexamatrix_stat,
    fetch_character_popularity,
    fetch_character_skill,
    fetch_character_stat,
    fetch_item_equipment,
    fetch_overall_ranking,
    fetch_set_effect,
    fetch_union,
    fetch_union_artifact,
    fetch_union_champion,
    fetch_union_raider,
    get_ocid,
    get_yesterday,
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


def _require_key():
    if not NEXON_API_KEY:
        raise HTTPException(status_code=500, detail="API 키가 설정되지 않았습니다.")


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


_HEXA_STAT_BLOCKS: tuple[tuple[str, str], ...] = (
    ("character_hexa_stat_core", "characterHexaStatCore"),
    ("character_hexa_stat_core_2", "characterHexaStatCore2"),
    ("character_hexa_stat_core_3", "characterHexaStatCore3"),
)


def _hexa_stat_slot_sort_key(s: HexaStatSlotUi) -> tuple[int, str]:
    sid = s.slotId or ""
    try:
        return (int(sid), sid)
    except ValueError:
        return (10**9, sid)


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


def _skills_from_character_skill_payload(payload: dict) -> list[dict[str, Any]]:
    raw = _nget(payload, "character_skill", "characterSkill")
    if not isinstance(raw, list):
        return []
    out = [_slim_skill_api_row(r) for r in raw if isinstance(r, dict)]
    return [r for r in out if _norm_skill_key(str(r.get("skillName") or ""))]


def _hexa_stat_slot_empty(slot: HexaStatSlotUi) -> bool:
    if (slot.main.level or 0) > 0:
        return False
    if _norm_skill_key(slot.main.name):
        return False
    for s in slot.subStats:
        if (s.level or 0) > 0:
            return False
        if _norm_skill_key(s.name):
            return False
    return True


def _hexa_stat_slot_from_row(row: dict) -> HexaStatSlotUi:
    main = HexaStatLineUi(
        name=_norm_skill_key(str(_nget(row, "main_stat_name", "mainStatName") or "")),
        level=_parse_int(_nget(row, "main_stat_level", "mainStatLevel")) or 0,
    )
    subs = [
        HexaStatLineUi(
            name=_norm_skill_key(
                str(_nget(row, "sub_stat_name_1", "subStatName1") or "")
            ),
            level=_parse_int(_nget(row, "sub_stat_level_1", "subStatLevel1")) or 0,
        ),
        HexaStatLineUi(
            name=_norm_skill_key(
                str(_nget(row, "sub_stat_name_2", "subStatName2") or "")
            ),
            level=_parse_int(_nget(row, "sub_stat_level_2", "subStatLevel2")) or 0,
        ),
    ]
    sid = _nget(row, "slot_id", "slotId")
    slot_s = str(sid).strip() if sid is not None else ""
    return HexaStatSlotUi(
        slotId=slot_s if slot_s else None,
        main=main,
        subStats=subs,
    )


def _hexa_stat_columns(payload: dict) -> list[HexaStatColumnUi]:
    cols: list[HexaStatColumnUi] = []
    for tier, (sk, ck) in enumerate(_HEXA_STAT_BLOCKS, start=1):
        block = _nget(payload, sk, ck)
        slots: list[HexaStatSlotUi] = []
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    sl = _hexa_stat_slot_from_row(item)
                    if not _hexa_stat_slot_empty(sl):
                        slots.append(sl)
        slots.sort(key=_hexa_stat_slot_sort_key)
        cols.append(
            HexaStatColumnUi(tier=cast(Literal[1, 2, 3], tier), slots=slots)
        )
    return cols


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
    _require_key()
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
            results = list(batch1) + [
                *batch2a[:3],
                *batch2b,
                *batch2a[3:],
            ] + list(batch3)
    except HTTPException:
        raise
    except httpx.RequestError as e:
        raise HTTPException(
            status_code=502,
            detail=(
                "넥슨 오픈 API에 연결하지 못했습니다. "
                f"({type(e).__name__}: {e}) "
                "VPN·회사 프록시·HTTP_PROXY 환경이면 비활성화 후 다시 시도하거나, "
                "방화벽에서 open.api.nexon.com 허용을 확인하세요."
            ),
        ) from e

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
    hexa_stat_raw = pick(13)
    job_sixth = [
        JobSkillUi.model_validate(x)
        for x in _skills_from_character_skill_payload(skill6_raw)
    ]
    job_fifth = [
        JobSkillUi.model_validate(x)
        for x in _skills_from_character_skill_payload(skill5_raw)
    ]
    hexa_stat_cols = _hexa_stat_columns(hexa_stat_raw)

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
        jobSkillSixth=job_sixth,
        jobSkillFifth=job_fifth,
        hexaStatColumns=hexa_stat_cols,
        union=union_detail,
    )
