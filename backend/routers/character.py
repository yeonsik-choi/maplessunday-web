import asyncio

import httpx
from fastapi import APIRouter, HTTPException

from core.config import NEXON_API_KEY
from schemas.character_all import CharacterAllResponse
from services.nexon_api import (
    get_ocid,
    get_yesterday,
    fetch_character_basic,
    fetch_character_stat,
    fetch_character_popularity,
    fetch_overall_ranking,
    fetch_item_equipment,
    fetch_union,
    fetch_union_raider,
    fetch_symbol_equipment,
)

router = APIRouter(prefix="/api", tags=["캐릭터"])

# 문서 기준 장비 필드만 통과 (넥슨 원본 키 이름)
_EQUIPMENT_KEYS = frozenset({
    "item_equipment_slot",
    "item_name",
    "item_icon",
    "item_description",
    "item_shape_name",
    "item_shape_icon",
    "item_gender",
    "date_expire",
    "starforce",
    "starforce_scroll_flag",
    "scroll_upgrade",
    "scroll_upgradeable_count",
    "scroll_resilience_count",
    "golden_hammer_flag",
    "cuttable_count",
    "item_total_option",
    "item_base_option",
    "item_add_option",
    "item_etc_option",
    "item_starforce_option",
    "item_exceptional_option",
    "potential_option_grade",
    "potential_option_1",
    "potential_option_2",
    "potential_option_3",
    "additional_potential_option_grade",
    "additional_potential_option_1",
    "additional_potential_option_2",
    "additional_potential_option_3",
    "soul_name",
    "soul_option",
    "special_ring_level",
    "equipment_level_increase",
})

_SYMBOL_KEYS = frozenset({
    "symbol_name",
    "symbol_icon",
    "symbol_force",
    "symbol_level",
    "symbol_str",
    "symbol_dex",
    "symbol_int",
    "symbol_luk",
    "symbol_hp",
    "symbol_growth_count",
    "symbol_require_growth_count",
})


def combat_power_from_stat(stat: dict):
    for s in stat.get("final_stat") or []:
        if isinstance(s, dict) and s.get("stat_name") == "전투력":
            return s.get("stat_value")
    return None


def filter_equipment_item(item: dict) -> dict:
    return {k: item[k] for k in _EQUIPMENT_KEYS if k in item}


def equipment_items_filtered(equip_data: dict) -> list[dict]:
    raw = equip_data.get("item_equipment") or []
    return [filter_equipment_item(dict(x)) for x in raw if isinstance(x, dict)]


def filter_symbol_row(row: dict) -> dict:
    return {k: row[k] for k in _SYMBOL_KEYS if k in row}


def symbol_rows_filtered(symbol_data: dict) -> list[dict]:
    raw = symbol_data.get("symbol") or []
    return [filter_symbol_row(dict(x)) for x in raw if isinstance(x, dict)]


def extract_overall_rank(
    ranking_payload: dict,
    character_name: str | None,
    world_name: str | None,
) -> int | None:
    if not ranking_payload or not character_name or not world_name:
        return None
    for row in ranking_payload.get("ranking") or []:
        if (
            row.get("character_name") == character_name
            and row.get("world_name") == world_name
        ):
            return row.get("ranking")
    return None


async def fetch_three_overall_ranks(
    client: httpx.AsyncClient,
    ocid: str,
    yesterday: str,
    basic: dict,
) -> tuple[int | None, int | None, int | None]:
    w = basic.get("world_name")
    c = basic.get("character_class")
    name = basic.get("character_name")

    async def safe_rank(world_name, class_name):
        try:
            return await fetch_overall_ranking(
                client, ocid, yesterday, world_name=world_name, class_name=class_name
            )
        except HTTPException:
            return {}

    overall_d, server_d, class_d = await asyncio.gather(
        safe_rank(None, None),
        safe_rank(w, None),
        safe_rank(w, c),
    )

    overall_r = extract_overall_rank(overall_d, name, w)
    server_r = extract_overall_rank(server_d, name, w)
    class_r = extract_overall_rank(class_d, name, w)
    return overall_r, server_r, class_r


def check_api_key():
    if not NEXON_API_KEY:
        raise HTTPException(status_code=500, detail="API 키가 설정되지 않았습니다.")


@router.get("/all", response_model=CharacterAllResponse)
async def get_all_info(nickname: str):
    """닉네임으로 문서에 정의된 필드만 한 번에 조회."""
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=30.0) as client:
        ocid = await get_ocid(client, nickname)

        results = await asyncio.gather(
            fetch_character_basic(client, ocid, yesterday),
            fetch_character_stat(client, ocid, yesterday),
            fetch_item_equipment(client, ocid, yesterday),
            fetch_union(client, ocid, yesterday),
            fetch_union_raider(client, ocid, yesterday),
            fetch_symbol_equipment(client, ocid, yesterday),
            fetch_character_popularity(client, ocid, yesterday),
            return_exceptions=True,
        )

        basic = results[0] if not isinstance(results[0], Exception) else {}
        stat = results[1] if not isinstance(results[1], Exception) else {}
        equip_data = results[2] if not isinstance(results[2], Exception) else {}
        union_data = results[3] if not isinstance(results[3], Exception) else {}
        raider_data = results[4] if not isinstance(results[4], Exception) else {}
        symbol_data = results[5] if not isinstance(results[5], Exception) else {}
        pop_raw = results[6] if not isinstance(results[6], Exception) else {}

        if basic:
            overall_rank_val, server_rank_val, class_rank_val = (
                await fetch_three_overall_ranks(client, ocid, yesterday, basic)
            )
        else:
            overall_rank_val = server_rank_val = class_rank_val = None

    popularity_val = None
    if isinstance(pop_raw, dict) and pop_raw:
        popularity_val = pop_raw.get("popularity")

    items = equipment_items_filtered(equip_data)
    symbols = symbol_rows_filtered(symbol_data)

    return {
        "character_image": basic.get("character_image"),
        "character_name": basic.get("character_name"),
        "world_name": basic.get("world_name"),
        "character_class": basic.get("character_class"),
        "character_guild_name": basic.get("character_guild_name"),
        "character_level": basic.get("character_level"),
        "character_exp_rate": basic.get("character_exp_rate"),
        "date": basic.get("date"),
        "popularity": popularity_val,
        "combat_power": combat_power_from_stat(stat),
        "overall_rank": overall_rank_val,
        "server_rank": server_rank_val,
        "class_rank": class_rank_val,
        "equipment": {"total_items": len(items), "items": items},
        "union": {
            "union_level": union_data.get("union_level"),
            "union_grade": union_data.get("union_grade"),
            "union_artifact_level": union_data.get("union_artifact_level"),
            "union_raider_stats": raider_data.get("union_raider_stat"),
            "union_occupied_stats": raider_data.get("union_occupied_stat"),
        },
        "symbols": {"total": len(symbols), "list": symbols},
    }
