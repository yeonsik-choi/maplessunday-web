import asyncio
import logging
import re

import httpx
from fastapi import APIRouter, HTTPException

from core.config import NEXON_API_KEY, NEXON_HTTP_TRUST_ENV
from schemas.character_all import (
    ArcaneRow,
    CharacterResponse,
    EquipTotalOptionUi,
    EquipUi,
    UnionUi,
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

# equips에 포함·정렬에 쓰는 슬롯만 (훈장·포켓·뱃지 등 제외)
_EQUIP_SLOTS: tuple[str, ...] = (
    "무기",
    "보조무기",
    "엠블렘",
    "모자",
    "얼굴장식",
    "눈장식",
    "귀고리",
    "상의",
    "하의",
    "장갑",
    "망토",
    "신발",
    "반지1",
    "반지2",
    "반지3",
    "반지4",
    "펜던트",
    "펜던트2",
    "벨트",
    "어깨장식",
)
_EQUIP_ORDER = {s: i for i, s in enumerate(_EQUIP_SLOTS)}

_ARCANE_NAMES = ("아케인포스", "아케인 포스")
_AUTH_NAMES = ("어센틱포스", "어센틱 포스")


def _equip_slot(item: dict) -> str:
    s = item.get("item_equipment_slot") or item.get("itemEquipmentSlot")
    return str(s).strip() if s is not None else ""


def _equip_rows(payload: dict) -> list:
    rows = payload.get("item_equipment") or payload.get("itemEquipment")
    return rows if isinstance(rows, list) else []


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


def _ability_lines(data: dict) -> tuple[str | None, str | None, str | None]:
    rows = data.get("ability_info") or []
    out: list[str | None] = [None, None, None]
    for i in range(3):
        if i < len(rows) and isinstance(rows[i], dict):
            v = rows[i].get("ability_value")
            if v is not None:
                out[i] = str(v)
    return out[0], out[1], out[2]


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
    return min(int(m.group(1)), 25) if m else 0


def _grade_class(raw) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
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
    if s in exact:
        return exact[s]
    low = s.lower()
    if low in exact:
        return exact[low]
    if "legend" in low or "레전" in s:
        return "legendary"
    if "unique" in low or "유니크" in s:
        return "unique"
    if "epic" in low or "에픽" in s:
        return "epic"
    if "rare" in low or "레어" in s:
        return "rare"
    return None


def _item_grade(item: dict) -> str | None:
    for key in ("potential_option_grade", "potentialOptionGrade"):
        g = _grade_class(item.get(key))
        if g:
            return g
    return None


def _item_additional_grade(item: dict) -> str | None:
    for key in ("additional_potential_option_grade", "additionalPotentialOptionGrade"):
        g = _grade_class(item.get(key))
        if g:
            return g
    return None


def _item_potential(item: dict) -> list[str]:
    out: list[str] = []
    for sk, ck in (
        ("potential_option_1", "potentialOption1"),
        ("potential_option_2", "potentialOption2"),
        ("potential_option_3", "potentialOption3"),
    ):
        v = item.get(sk)
        if v is None:
            v = item.get(ck)
        if v is None:
            continue
        t = str(v).strip()
        if t:
            out.append(t)
    return out


def _item_additional_potential(item: dict) -> list[str]:
    out: list[str] = []
    for sk, ck in (
        ("additional_potential_option_1", "additionalPotentialOption1"),
        ("additional_potential_option_2", "additionalPotentialOption2"),
        ("additional_potential_option_3", "additionalPotentialOption3"),
    ):
        v = item.get(sk)
        if v is None:
            v = item.get(ck)
        if v is None:
            continue
        t = str(v).strip()
        if t:
            out.append(t)
    return out


def _subdoc(item: dict, snake: str, camel: str) -> dict | None:
    v = item.get(snake)
    if v is None:
        v = item.get(camel)
    return v if isinstance(v, dict) else None


def _item_str_top(item: dict, snake: str, camel: str) -> str | None:
    for k in (snake, camel):
        v = item.get(k)
        if v is not None:
            t = str(v).strip()
            if t:
                return t
    return None


def _nested_str(parent: dict | None, snake: str, camel: str) -> str | None:
    if not parent:
        return None
    for k in (snake, camel):
        v = parent.get(k)
        if v is not None:
            t = str(v).strip()
            if t:
                return t
    return None


def _total_option_ui(item: dict) -> EquipTotalOptionUi | None:
    raw = _subdoc(item, "item_total_option", "itemTotalOption")
    if not raw:
        return None

    def g(sn: str, *cams: str) -> str | None:
        for k in (sn,) + cams:
            v = raw.get(k)
            if v is not None:
                t = str(v).strip()
                if t:
                    return t
        return None

    ui = EquipTotalOptionUi(
        str_bonus=g("str", "STR"),
        dex=g("dex", "DEX"),
        int_bonus=g("int", "INT"),
        luk=g("luk", "LUK"),
        max_hp=g("max_hp", "maxHp"),
        max_mp=g("max_mp", "maxMp"),
        attack_power=g("attack_power", "attackPower"),
        magic_power=g("magic_power", "magicPower"),
        armor=g("armor"),
        ignore_monster_armor=g("ignore_monster_armor", "ignoreMonsterArmor"),
        all_stat=g("all_stat", "allStat"),
        boss_damage=g("boss_damage", "bossDamage"),
    )
    if not ui.model_dump(exclude_none=True):
        return None
    return ui


def _to_equip(item: dict) -> EquipUi:
    name = item.get("item_name")
    if name is None:
        name = item.get("itemName")
    pots = _item_potential(item)
    add_pots = _item_additional_potential(item)
    base_block = _subdoc(item, "item_base_option", "itemBaseOption")
    base_lv = _nested_str(
        base_block, "base_equipment_level", "baseEquipmentLevel"
    )
    total_opt = _total_option_ui(item)
    apots = add_pots if add_pots else None

    return EquipUi(
        slot=_equip_slot(item) or None,
        name=name,
        stars=_parse_stars(item.get("starforce")),
        grade=_item_grade(item),
        potential=pots if pots else None,
        item_icon=_item_str_top(item, "item_icon", "itemIcon"),
        base_equipment_level=base_lv,
        scroll_upgrade=_item_str_top(item, "scroll_upgrade", "scrollUpgrade"),
        additional_grade=_item_additional_grade(item),
        additional_potential=apots,
        total_option=total_opt,
        base_option=base_block,
        add_option=_subdoc(item, "item_add_option", "itemAddOption"),
        etc_option=_subdoc(item, "item_etc_option", "itemEtcOption"),
        starforce_option=_subdoc(
            item, "item_starforce_option", "itemStarforceOption"
        ),
        scroll_upgradeable_count=_item_str_top(
            item, "scroll_upgradeable_count", "scrollUpgradeableCount"
        ),
        scroll_resilience_count=_item_str_top(
            item, "scroll_resilience_count", "scrollResilienceCount"
        ),
        cuttable_count=_item_str_top(item, "cuttable_count", "cuttableCount"),
        soul_name=_item_str_top(item, "soul_name", "soulName"),
        soul_option=_item_str_top(item, "soul_option", "soulOption"),
        shape_name=_item_str_top(item, "item_shape_name", "itemShapeName"),
    )


@router.get(
    "/character",
    response_model=CharacterResponse,
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
            await asyncio.sleep(1.0)
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
            logger.warning("nexon fetch failed idx=%s: %s", i, r)

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

    rows = [
        row
        for row in _equip_rows(equip_data)
        if isinstance(row, dict) and _equip_slot(row) in _EQUIP_ORDER
    ]
    rows.sort(key=lambda r: _EQUIP_ORDER[_equip_slot(r)])
    equips = [_to_equip(r) for r in rows]

    af = _final_stat_int(stat, _ARCANE_NAMES)
    tf = _final_stat_int(stat, _AUTH_NAMES)
    ab1, ab2, ab3 = _ability_lines(ability_data)
    abilities = [ab1 or "", ab2 or "", ab3 or ""]

    arcane: list[ArcaneRow] = []
    if af is not None:
        arcane.append(ArcaneRow(k="아케인포스", v=f"{af:,}"))
    if tf is not None:
        arcane.append(ArcaneRow(k="어센틱포스", v=f"{tf:,}"))

    combat = _combat_power_raw(stat)
    disp = _fmt_combat_display(combat) if combat else ""

    rank_n = _rank_int(rank_data)
    pop_n = pop_data.get("popularity")
    union_n = union_data.get("union_level")
    if union_n is None:
        union_n = union_data.get("unionLevel")
    union_level_str = _fmt_thousands(union_n) if union_n is not None else None

    return CharacterResponse(
        imageUrl=basic.get("character_image"),
        name=basic.get("character_name"),
        level=_coerce_level(basic.get("character_level")),
        world=basic.get("world_name"),
        job=basic.get("character_class"),
        ranking=_fmt_thousands(rank_n),
        popularity=_fmt_thousands(pop_n) if pop_n is not None else None,
        union=UnionUi(level=union_level_str),
        unionLevel=union_level_str,
        guild=basic.get("character_guild_name") or "",
        expPercent=_parse_exp_pct(basic.get("character_exp_rate")),
        combatPower=disp or None,
        arcaneForce=f"{af:,}" if af is not None else None,
        authenticForce=f"{tf:,}" if tf is not None else None,
        arcane=arcane,
        abilities=abilities,
        equips=equips,
    )
