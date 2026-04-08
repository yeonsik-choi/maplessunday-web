import asyncio
import logging
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from core.config import NEXON_API_KEY, NEXON_HTTP_TRUST_ENV
from schemas.character_all import (
    AbilityPresetUi,
    ArcaneRow,
    CharacterResponse,
    EquipTotalOptionUi,
    EquipUi,
)
from services.nexon_api import (
    fetch_character_ability,
    fetch_character_basic,
    fetch_character_popularity,
    fetch_character_stat,
    fetch_item_equipment,
    fetch_overall_ranking,
    fetch_union,
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
    "ranking",
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
            batch2 = await asyncio.gather(
                fetch_item_equipment(client, ocid, yesterday),
                fetch_character_popularity(client, ocid, yesterday),
                fetch_union(client, ocid, yesterday),
                fetch_overall_ranking(client, ocid, yesterday),
                return_exceptions=True,
            )
            results = list(batch1) + list(batch2)
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
    rank_data = pick(6)

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
        equipmentPresetNo=equipment_preset_no,
        equipsPreset1=ep0,
        equipsPreset2=ep1,
        equipsPreset3=ep2,
        abilityPresetNo=ability_preset_no,
        abilityPreset1=ap1,
        abilityPreset2=ap2,
        abilityPreset3=ap3,
    )
