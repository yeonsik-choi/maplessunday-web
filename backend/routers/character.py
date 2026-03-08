import asyncio

import httpx
from fastapi import APIRouter, HTTPException

from core.config import NEXON_API_KEY
from services.nexon_api import (
    get_ocid,
    get_yesterday,
    fetch_character_basic,
    fetch_character_stat,
    fetch_item_equipment,
    fetch_union,
    fetch_union_raider,
    fetch_hyper_stat,
    fetch_symbol_equipment,
    fetch_ability,
)

router = APIRouter(prefix="/api", tags=["캐릭터"])


def check_api_key():
    """API 키가 설정되어 있는지 확인"""
    if not NEXON_API_KEY:
        raise HTTPException(status_code=500, detail="API 키가 설정되지 않았습니다.")


# ============================================================
# 캐릭터 기본 정보 + 스탯 검색
# ============================================================
@router.get("/search")
async def search_character(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)

        basic, stat = await asyncio.gather(
            fetch_character_basic(client, ocid, yesterday),
            fetch_character_stat(client, ocid, yesterday),
        )

    # 주요 스탯 추출
    combat_power = None
    main_stats = []

    for s in stat.get("final_stat", []):
        if s["stat_name"] == "전투력":
            combat_power = s["stat_value"]
        if s["stat_name"] in [
            "전투력", "STR", "DEX", "INT", "LUK",
            "최대 HP", "최대 MP",
            "공격력", "마력",
            "스타포스", "보스 몬스터 데미지",
            "방어율 무시", "크리티컬 확률", "크리티컬 데미지",
        ]:
            main_stats.append({
                "name": s["stat_name"],
                "value": s["stat_value"],
            })

    return {
        "character_name": basic.get("character_name"),
        "character_level": basic.get("character_level"),
        "character_class": basic.get("character_class"),
        "world_name": basic.get("world_name"),
        "character_image": basic.get("character_image"),
        "character_gender": basic.get("character_gender"),
        "character_guild_name": basic.get("character_guild_name"),
        "character_exp_rate": basic.get("character_exp_rate"),
        "combat_power": combat_power,
        "main_stats": main_stats,
        "date": basic.get("date"),
    }


# ============================================================
# 장비 정보 조회
# ============================================================
@router.get("/equipment")
async def get_equipment(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)
        equip_data = await fetch_item_equipment(client, ocid, yesterday)

    items = []
    for item in equip_data.get("item_equipment", []):
        items.append({
            "slot": item.get("item_equipment_slot"),
            "name": item.get("item_name"),
            "icon": item.get("item_icon"),
            "starforce": item.get("starforce"),
            "potential_option_grade": item.get("potential_option_grade"),
            "potential_option_1": item.get("potential_option_1"),
            "potential_option_2": item.get("potential_option_2"),
            "potential_option_3": item.get("potential_option_3"),
            "additional_potential_option_grade": item.get("additional_potential_option_grade"),
            "additional_potential_option_1": item.get("additional_potential_option_1"),
            "additional_potential_option_2": item.get("additional_potential_option_2"),
            "additional_potential_option_3": item.get("additional_potential_option_3"),
            "scroll_upgrade": item.get("scroll_upgrade"),
        })

    return {
        "character_name": nickname,
        "date": equip_data.get("date"),
        "total_items": len(items),
        "items": items,
    }


# ============================================================
# 유니온 정보 조회
# ============================================================
@router.get("/union")
async def get_union_info(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)

        union_data, raider_data = await asyncio.gather(
            fetch_union(client, ocid, yesterday),
            fetch_union_raider(client, ocid, yesterday),
        )

    return {
        "character_name": nickname,
        "date": union_data.get("date"),
        "union_level": union_data.get("union_level"),
        "union_grade": union_data.get("union_grade"),
        "union_artifact_level": union_data.get("union_artifact_level"),
        "union_artifact_exp": union_data.get("union_artifact_exp"),
        "union_artifact_point": union_data.get("union_artifact_point"),
        "union_raider_stats": raider_data.get("union_raider_stat"),
        "union_occupied_stats": raider_data.get("union_occupied_stat"),
    }


# ============================================================
# 하이퍼스탯 조회
# ============================================================
@router.get("/hyper-stat")
async def get_hyper_stat(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)
        data = await fetch_hyper_stat(client, ocid, yesterday)

    return {
        "character_name": nickname,
        "date": data.get("date"),
        "use_preset_no": data.get("use_preset_no"),
        "hyper_stat_preset_1": data.get("hyper_stat_preset_1"),
        "hyper_stat_preset_2": data.get("hyper_stat_preset_2"),
        "hyper_stat_preset_3": data.get("hyper_stat_preset_3"),
    }


# ============================================================
# 심볼 장비 조회
# ============================================================
@router.get("/symbol")
async def get_symbol(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)
        data = await fetch_symbol_equipment(client, ocid, yesterday)

    symbols = []
    for s in data.get("symbol", []):
        symbols.append({
            "name": s.get("symbol_name"),
            "icon": s.get("symbol_icon"),
            "force": s.get("symbol_force"),
            "level": s.get("symbol_level"),
            "str": s.get("symbol_str"),
            "dex": s.get("symbol_dex"),
            "int": s.get("symbol_int"),
            "luk": s.get("symbol_luk"),
            "hp": s.get("symbol_hp"),
            "growth_count": s.get("symbol_growth_count"),
            "require_growth_count": s.get("symbol_require_growth_count"),
        })

    return {
        "character_name": nickname,
        "date": data.get("date"),
        "character_class": data.get("character_class"),
        "total_symbols": len(symbols),
        "symbols": symbols,
    }


# ============================================================
# 어빌리티 조회
# ============================================================
@router.get("/ability")
async def get_ability(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)
        data = await fetch_ability(client, ocid, yesterday)

    return {
        "character_name": nickname,
        "date": data.get("date"),
        "ability_grade": data.get("ability_grade"),
        "ability_info": data.get("ability_info"),
        "remain_fame": data.get("remain_fame"),
        "preset_no": data.get("preset_no"),
        "ability_preset_1": data.get("ability_preset_1"),
        "ability_preset_2": data.get("ability_preset_2"),
        "ability_preset_3": data.get("ability_preset_3"),
    }

# ============================================================
# 전체 정보 한번에 조회 (통합)
# ============================================================
@router.get("/all")
async def get_all_info(nickname: str):
    """닉네임 하나로 모든 정보를 한번에 조회한다."""
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=15.0) as client:
        ocid = await get_ocid(client, nickname)

        # 8개 API 동시 호출 (일부 실패해도 나머지는 반환)
        results = await asyncio.gather(
            fetch_character_basic(client, ocid, yesterday),
            fetch_character_stat(client, ocid, yesterday),
            fetch_item_equipment(client, ocid, yesterday),
            fetch_union(client, ocid, yesterday),
            fetch_union_raider(client, ocid, yesterday),
            fetch_hyper_stat(client, ocid, yesterday),
            fetch_symbol_equipment(client, ocid, yesterday),
            fetch_ability(client, ocid, yesterday),
            return_exceptions=True,
        )

        basic = results[0] if not isinstance(results[0], Exception) else {}
        stat = results[1] if not isinstance(results[1], Exception) else {}
        equip_data = results[2] if not isinstance(results[2], Exception) else {}
        union_data = results[3] if not isinstance(results[3], Exception) else {}
        raider_data = results[4] if not isinstance(results[4], Exception) else {}
        hyper_data = results[5] if not isinstance(results[5], Exception) else {}
        symbol_data = results[6] if not isinstance(results[6], Exception) else {}
        ability_data = results[7] if not isinstance(results[7], Exception) else {}

    # 스탯 정리
    combat_power = None
    main_stats = []
    for s in stat.get("final_stat", []):  
        if s["stat_name"] == "전투력":
            combat_power = s["stat_value"]
        if s["stat_name"] in [
            "전투력", "STR", "DEX", "INT", "LUK",
            "최대 HP", "최대 MP",
            "공격력", "마력",
            "스타포스", "보스 몬스터 데미지",
            "방어율 무시", "크리티컬 확률", "크리티컬 데미지",
        ]:
            main_stats.append({"name": s["stat_name"], "value": s["stat_value"]})

    # 장비 정리
    items = []
    for item in equip_data.get("item_equipment", []):
        items.append({
            "slot": item.get("item_equipment_slot"),
            "name": item.get("item_name"),
            "icon": item.get("item_icon"),
            "starforce": item.get("starforce"),
            "potential_option_grade": item.get("potential_option_grade"),
            "potential_option_1": item.get("potential_option_1"),
            "potential_option_2": item.get("potential_option_2"),
            "potential_option_3": item.get("potential_option_3"),
            "additional_potential_option_grade": item.get("additional_potential_option_grade"),
            "additional_potential_option_1": item.get("additional_potential_option_1"),
            "additional_potential_option_2": item.get("additional_potential_option_2"),
            "additional_potential_option_3": item.get("additional_potential_option_3"),
            "scroll_upgrade": item.get("scroll_upgrade"),
        })

    # 심볼 정리
    symbols = []
    for s in symbol_data.get("symbol", []):
        symbols.append({
            "name": s.get("symbol_name"),
            "icon": s.get("symbol_icon"),
            "force": s.get("symbol_force"),
            "level": s.get("symbol_level"),
            "str": s.get("symbol_str"),
            "dex": s.get("symbol_dex"),
            "int": s.get("symbol_int"),
            "luk": s.get("symbol_luk"),
            "hp": s.get("symbol_hp"),
        })

    return {
        # 기본 정보
        "character_name": basic.get("character_name"),
        "character_level": basic.get("character_level"),
        "character_class": basic.get("character_class"),
        "world_name": basic.get("world_name"),
        "character_image": basic.get("character_image"),
        "character_gender": basic.get("character_gender"),
        "character_guild_name": basic.get("character_guild_name"),
        "date": basic.get("date"),
        # 스탯
        "combat_power": combat_power,
        "main_stats": main_stats,
        # 장비
        "equipment": {"total_items": len(items), "items": items},
        # 유니온
        "union": {
            "union_level": union_data.get("union_level"),
            "union_grade": union_data.get("union_grade"),
            "union_artifact_level": union_data.get("union_artifact_level"),
            "union_raider_stats": raider_data.get("union_raider_stat"),
            "union_occupied_stats": raider_data.get("union_occupied_stat"),
        },
        # 하이퍼스탯
        "hyper_stat": {
            "use_preset_no": hyper_data.get("use_preset_no"),
            "preset_1": hyper_data.get("hyper_stat_preset_1"),
            "preset_2": hyper_data.get("hyper_stat_preset_2"),
            "preset_3": hyper_data.get("hyper_stat_preset_3"),
        },
        # 심볼
        "symbols": {"total": len(symbols), "list": symbols},
        # 어빌리티
        "ability": {
            "grade": ability_data.get("ability_grade"),
            "info": ability_data.get("ability_info"),
            "preset_1": ability_data.get("ability_preset_1"),
            "preset_2": ability_data.get("ability_preset_2"),
            "preset_3": ability_data.get("ability_preset_3"),
        },
    }
