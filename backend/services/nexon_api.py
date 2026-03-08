import asyncio
from datetime import datetime, timedelta

import httpx
from fastapi import HTTPException

from core.config import BASE_URL, HEADERS


def get_yesterday() -> str:
    """어제 날짜를 YYYY-MM-DD 형식으로 반환"""
    yesterday = datetime.now() - timedelta(days=2)
    return yesterday.strftime("%Y-%m-%d")


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
    response = await client.get(
        f"{BASE_URL}/character/basic",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="캐릭터 기본 정보 조회 실패")
    return response.json()


async def fetch_character_stat(client: httpx.AsyncClient, ocid: str, date: str):
    """캐릭터 스탯 조회"""
    response = await client.get(
        f"{BASE_URL}/character/stat",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="캐릭터 스탯 조회 실패")
    return response.json()


async def fetch_item_equipment(client: httpx.AsyncClient, ocid: str, date: str):
    """장비 정보 조회"""
    response = await client.get(
        f"{BASE_URL}/character/item-equipment",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="장비 정보 조회 실패")
    return response.json()


async def fetch_union(client: httpx.AsyncClient, ocid: str, date: str):
    """유니온 기본 정보 조회"""
    response = await client.get(
        f"{BASE_URL}/user/union",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="유니온 정보 조회 실패")
    return response.json()


async def fetch_union_raider(client: httpx.AsyncClient, ocid: str, date: str):
    """유니온 공격대 정보 조회"""
    response = await client.get(
        f"{BASE_URL}/user/union-raider",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="유니온 공격대 정보 조회 실패")
    return response.json()


async def fetch_hyper_stat(client: httpx.AsyncClient, ocid: str, date: str):
    """하이퍼스탯 조회"""
    response = await client.get(
        f"{BASE_URL}/character/hyper-stat",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="하이퍼스탯 조회 실패")
    return response.json()


async def fetch_symbol_equipment(client: httpx.AsyncClient, ocid: str, date: str):
    """심볼 장비 조회"""
    response = await client.get(
        f"{BASE_URL}/character/symbol-equipment",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="심볼 정보 조회 실패")
    return response.json()


async def fetch_ability(client: httpx.AsyncClient, ocid: str, date: str):
    """어빌리티 조회"""
    response = await client.get(
        f"{BASE_URL}/character/ability",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="어빌리티 조회 실패")
    return response.json()


async def fetch_set_effect(client: httpx.AsyncClient, ocid: str, date: str):
    """세트 효과 조회"""
    response = await client.get(
        f"{BASE_URL}/character/set-effect",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="세트 효과 조회 실패")
    return response.json()


async def fetch_link_skill(client: httpx.AsyncClient, ocid: str, date: str):
    """링크 스킬 조회"""
    response = await client.get(
        f"{BASE_URL}/character/link-skill",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="링크 스킬 조회 실패")
    return response.json()


async def fetch_hexamatrix(client: httpx.AsyncClient, ocid: str, date: str):
    """HEXA 스킬 조회"""
    response = await client.get(
        f"{BASE_URL}/character/hexamatrix",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="HEXA 스킬 조회 실패")
    return response.json()


async def fetch_hexamatrix_stat(client: httpx.AsyncClient, ocid: str, date: str):
    """HEXA 스탯 조회"""
    response = await client.get(
        f"{BASE_URL}/character/hexamatrix-stat",
        headers=HEADERS,
        params={"ocid": ocid, "date": date},
    )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail="HEXA 스탯 조회 실패")
    return response.json()
