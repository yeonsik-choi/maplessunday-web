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
    fetch_hyper_stat,
    fetch_symbol_equipment,
    fetch_ability,
    fetch_set_effect,
    fetch_link_skill,
    fetch_hexamatrix,
    fetch_hexamatrix_stat,
)

router = APIRouter(prefix="/api", tags=["캐릭터"])

MAIN_STAT_NAMES = frozenset({
    "전투력", "STR", "DEX", "INT", "LUK",
    "최대 HP", "최대 MP",
    "공격력", "마력",
    "스타포스", "보스 몬스터 데미지",
    "방어율 무시", "크리티컬 확률", "크리티컬 데미지",
})


def combat_power_and_main_stats(stat: dict):
    combat_power = None
    main_stats = []
    for s in stat.get("final_stat", []):
        if s["stat_name"] == "전투력":
            combat_power = s["stat_value"]
        if s["stat_name"] in MAIN_STAT_NAMES:
            main_stats.append({"name": s["stat_name"], "value": s["stat_value"]})
    return combat_power, main_stats


def equipment_items_from_nexon(equip_data: dict) -> list:
    """넥슨 character/item-equipment 의 item_equipment 원본 객체 목록 (필드 그대로)."""
    raw = equip_data.get("item_equipment") or []
    return [dict(x) for x in raw if isinstance(x, dict)]


def symbol_rows_from_nexon(symbol_data: dict) -> list:
    """넥슨 symbol-equipment 의 symbol 원본 객체 목록 (symbol_name, symbol_icon 등 그대로)."""
    raw = symbol_data.get("symbol") or []
    return [dict(x) for x in raw if isinstance(x, dict)]


def extract_overall_rank(
    ranking_payload: dict,
    character_name: str | None,
    world_name: str | None,
) -> int | None:
    """종합 랭킹 응답에서 캐릭터(이름+월드 일치) 순위를 찾는다. 첫 페이지에 없으면 None."""
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
) -> tuple[int | None, int | None, int | None, str | None]:
    """종합 / 서버(월드) / 직업(월드+직업) 필터별 종합 랭킹 순위. 실패 시 None."""
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

    rd = (
        overall_d.get("date")
        or server_d.get("date")
        or class_d.get("date")
    )
    return overall_r, server_r, class_r, rd


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

    async with httpx.AsyncClient(timeout=12.0) as client:
        ocid = await get_ocid(client, nickname)

        basic, stat = await asyncio.gather(
            fetch_character_basic(client, ocid, yesterday),
            fetch_character_stat(client, ocid, yesterday),
        )

        popularity = None
        popularity_date = None
        try:
            pop = await fetch_character_popularity(client, ocid, yesterday)
            popularity = pop.get("popularity")
            popularity_date = pop.get("date")
        except HTTPException:
            pass

        if basic:
            overall_rank, server_rank, class_rank, ranking_date = (
                await fetch_three_overall_ranks(client, ocid, yesterday, basic)
            )
        else:
            overall_rank = server_rank = class_rank = ranking_date = None

    combat_power, main_stats = combat_power_and_main_stats(stat)

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
        "popularity": popularity,
        "popularity_date": popularity_date,
        "overall_rank": overall_rank,
        "server_rank": server_rank,
        "class_rank": class_rank,
        "ranking_date": ranking_date,
    }


# ============================================================
# 인기도 조회
# ============================================================
@router.get("/popularity")
async def get_popularity(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)
        data = await fetch_character_popularity(client, ocid, yesterday)

    return {
        "character_name": nickname,
        "date": data.get("date"),
        "popularity": data.get("popularity"),
    }


# ============================================================
# 종합 랭킹 (해당 캐릭터 순위)
# ============================================================
@router.get("/ranking-overall")
async def get_ranking_overall(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=15.0) as client:
        ocid = await get_ocid(client, nickname)
        basic = await fetch_character_basic(client, ocid, yesterday)
        overall_rank, server_rank, class_rank, ranking_date = (
            await fetch_three_overall_ranks(client, ocid, yesterday, basic)
        )

    return {
        "character_name": basic.get("character_name"),
        "world_name": basic.get("world_name"),
        "character_class": basic.get("character_class"),
        "date": ranking_date,
        "overall_rank": overall_rank,
        "server_rank": server_rank,
        "class_rank": class_rank,
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

    items = equipment_items_from_nexon(equip_data)

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

    symbols = symbol_rows_from_nexon(data)

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
@router.get("/all", response_model=CharacterAllResponse)
async def get_all_info(nickname: str):
    """닉네임 하나로 모든 정보를 한번에 조회한다."""
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=30.0) as client:
        ocid = await get_ocid(client, nickname)

        # 13개 API 동시 호출 (일부 실패해도 나머지는 반환)
        results = await asyncio.gather(
            fetch_character_basic(client, ocid, yesterday),
            fetch_character_stat(client, ocid, yesterday),
            fetch_item_equipment(client, ocid, yesterday),
            fetch_union(client, ocid, yesterday),
            fetch_union_raider(client, ocid, yesterday),
            fetch_hyper_stat(client, ocid, yesterday),
            fetch_symbol_equipment(client, ocid, yesterday),
            fetch_ability(client, ocid, yesterday),
            fetch_set_effect(client, ocid, yesterday),
            fetch_link_skill(client, ocid, yesterday),
            fetch_hexamatrix(client, ocid, yesterday),
            fetch_hexamatrix_stat(client, ocid, yesterday),
            fetch_character_popularity(client, ocid, yesterday),
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
        set_effect_data = results[8] if not isinstance(results[8], Exception) else {}
        link_skill_data = results[9] if not isinstance(results[9], Exception) else {}
        hexa_data = results[10] if not isinstance(results[10], Exception) else {}
        hexa_stat_data = results[11] if not isinstance(results[11], Exception) else {}
        pop_raw = results[12] if not isinstance(results[12], Exception) else {}

        if basic:
            overall_rank_val, server_rank_val, class_rank_val, ranking_date_val = (
                await fetch_three_overall_ranks(client, ocid, yesterday, basic)
            )
        else:
            overall_rank_val = server_rank_val = class_rank_val = ranking_date_val = None

    combat_power, main_stats = combat_power_and_main_stats(stat)
    items = equipment_items_from_nexon(equip_data)
    symbols = symbol_rows_from_nexon(symbol_data)

    popularity_val = None
    popularity_date_val = None
    if isinstance(pop_raw, dict) and pop_raw:
        popularity_val = pop_raw.get("popularity")
        popularity_date_val = pop_raw.get("date")

    return {
        # 기본 정보
        "character_name": basic.get("character_name"),
        "character_level": basic.get("character_level"),
        "character_class": basic.get("character_class"),
        "world_name": basic.get("world_name"),
        "character_image": basic.get("character_image"),
        "character_gender": basic.get("character_gender"),
        "character_guild_name": basic.get("character_guild_name"),
        "character_exp_rate": basic.get("character_exp_rate"),
        "date": basic.get("date"),
        "popularity": popularity_val,
        "popularity_date": popularity_date_val,
        "overall_rank": overall_rank_val,
        "server_rank": server_rank_val,
        "class_rank": class_rank_val,
        "ranking_date": ranking_date_val,
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
        # 세트 효과
        "set_effect": set_effect_data.get("set_effect"),
        # 링크 스킬
        "link_skill": link_skill_data.get("character_link_skill"),
        # HEXA
        "hexamatrix": hexa_data.get("character_hexa_core_equipment"),
        "hexamatrix_stat": hexa_stat_data.get("character_hexa_stat_core"),
    }


# ============================================================
# 세트 효과 조회
# ============================================================
@router.get("/set-effect")
async def get_set_effect(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)
        data = await fetch_set_effect(client, ocid, yesterday)

    return {
        "character_name": nickname,
        "date": data.get("date"),
        "set_effect": data.get("set_effect"),
    }


# ============================================================
# 링크 스킬 조회
# ============================================================
@router.get("/link-skill")
async def get_link_skill(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)
        data = await fetch_link_skill(client, ocid, yesterday)

    return {
        "character_name": nickname,
        "date": data.get("date"),
        "character_class": data.get("character_class"),
        "character_link_skill": data.get("character_link_skill"),
        "character_link_skill_preset_1": data.get("character_link_skill_preset_1"),
        "character_link_skill_preset_2": data.get("character_link_skill_preset_2"),
        "character_link_skill_preset_3": data.get("character_link_skill_preset_3"),
        "character_owned_link_skill": data.get("character_owned_link_skill"),
    }


# ============================================================
# HEXA 스킬 조회
# ============================================================
@router.get("/hexamatrix")
async def get_hexamatrix(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)
        data = await fetch_hexamatrix(client, ocid, yesterday)

    return {
        "character_name": nickname,
        "date": data.get("date"),
        "character_hexa_core_equipment": data.get("character_hexa_core_equipment"),
    }


# ============================================================
# HEXA 스탯 조회
# ============================================================
@router.get("/hexamatrix-stat")
async def get_hexamatrix_stat(nickname: str):
    check_api_key()
    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:
        ocid = await get_ocid(client, nickname)
        data = await fetch_hexamatrix_stat(client, ocid, yesterday)

    return {
        "character_name": nickname,
        "date": data.get("date"),
        "character_hexa_stat_core": data.get("character_hexa_stat_core"),
        "preset_hexa_stat_core": data.get("preset_hexa_stat_core"),
    }
