from datetime import datetime, timedelta

import httpx
from fastapi import HTTPException

from core.config import BASE_URL, HEADERS


def get_yesterday() -> str:
    """어제 날짜를 YYYY-MM-DD 형식으로 반환"""
    yesterday = datetime.now() - timedelta(days=2)
    return yesterday.strftime("%Y-%m-%d")


async def _fetch_ocid_date(
    client: httpx.AsyncClient,
    subpath: str,
    ocid: str,
    date: str,
    error_detail: str,
) -> dict:
    response = await client.get(
        f"{BASE_URL}/{subpath}",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=error_detail)
    return response.json()


async def get_ocid(client: httpx.AsyncClient, nickname: str) -> str:
    """닉네임으로 OCID를 조회한다."""
    response = await client.get(
        f"{BASE_URL}/id",
        headers=HEADERS,
        params={"character_name": nickname},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=404, detail=f"'{nickname}' 캐릭터를 찾을 수 없습니다.")
    return response.json()["ocid"]


async def fetch_character_basic(client: httpx.AsyncClient, ocid: str, date: str):
    """캐릭터 기본 정보 조회"""
    return await _fetch_ocid_date(client, "character/basic", ocid, date, "캐릭터 기본 정보 조회 실패")


async def fetch_character_stat(client: httpx.AsyncClient, ocid: str, date: str):
    """캐릭터 스탯 조회"""
    return await _fetch_ocid_date(client, "character/stat", ocid, date, "캐릭터 스탯 조회 실패")


async def fetch_character_popularity(client: httpx.AsyncClient, ocid: str, date: str):
    """캐릭터 인기도 조회"""
    return await _fetch_ocid_date(client, "character/popularity", ocid, date, "캐릭터 인기도 조회 실패")


async def fetch_overall_ranking(
    client: httpx.AsyncClient,
    ocid: str,
    date: str,
    world_name: str | None = None,
    class_name: str | None = None,
    page: int = 1,
):
    """종합 랭킹 조회 (ocid·월드·직업으로 필터, 응답 ranking 목록에서 해당 캐릭터 매칭)"""
    params: dict = {"ocid": ocid, "date": date, "page": page}
    if world_name:
        params["world_name"] = world_name
    if class_name:
        params["class"] = class_name
    response = await client.get(
        f"{BASE_URL}/ranking/overall",
        headers=HEADERS,
        params=params,
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="종합 랭킹 조회 실패")
    return response.json()


async def fetch_item_equipment(client: httpx.AsyncClient, ocid: str, date: str):
    """장비 정보 조회"""
    return await _fetch_ocid_date(client, "character/item-equipment", ocid, date, "장비 정보 조회 실패")


async def fetch_union(client: httpx.AsyncClient, ocid: str, date: str):
    """유니온 기본 정보 조회"""
    return await _fetch_ocid_date(client, "user/union", ocid, date, "유니온 정보 조회 실패")


async def fetch_union_raider(client: httpx.AsyncClient, ocid: str, date: str):
    """유니온 공격대 정보 조회"""
    return await _fetch_ocid_date(client, "user/union-raider", ocid, date, "유니온 공격대 정보 조회 실패")


async def fetch_hyper_stat(client: httpx.AsyncClient, ocid: str, date: str):
    """하이퍼스탯 조회"""
    return await _fetch_ocid_date(client, "character/hyper-stat", ocid, date, "하이퍼스탯 조회 실패")


async def fetch_symbol_equipment(client: httpx.AsyncClient, ocid: str, date: str):
    """심볼 장비 조회"""
    return await _fetch_ocid_date(client, "character/symbol-equipment", ocid, date, "심볼 정보 조회 실패")


async def fetch_ability(client: httpx.AsyncClient, ocid: str, date: str):
    """어빌리티 조회"""
    return await _fetch_ocid_date(client, "character/ability", ocid, date, "어빌리티 조회 실패")


async def fetch_set_effect(client: httpx.AsyncClient, ocid: str, date: str):
    """세트 효과 조회"""
    return await _fetch_ocid_date(client, "character/set-effect", ocid, date, "세트 효과 조회 실패")


async def fetch_link_skill(client: httpx.AsyncClient, ocid: str, date: str):
    """링크 스킬 조회"""
    return await _fetch_ocid_date(client, "character/link-skill", ocid, date, "링크 스킬 조회 실패")


async def fetch_hexamatrix(client: httpx.AsyncClient, ocid: str, date: str):
    """HEXA 스킬 조회"""
    return await _fetch_ocid_date(client, "character/hexamatrix", ocid, date, "HEXA 스킬 조회 실패")


async def fetch_hexamatrix_stat(client: httpx.AsyncClient, ocid: str, date: str):
    """HEXA 스탯 조회"""
    return await _fetch_ocid_date(client, "character/hexamatrix-stat", ocid, date, "HEXA 스탯 조회 실패")
