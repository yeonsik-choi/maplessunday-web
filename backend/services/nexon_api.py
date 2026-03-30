from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException

from core.config import BASE_URL, HEADERS

KST = ZoneInfo("Asia/Seoul")


def _raise_for_failed_nexon(response: httpx.Response, error_detail: str) -> None:
    """넥슨이 200이 아닐 때. 429는 그대로 전달해 rate limit 여부를 구분 가능하게 한다."""
    code = response.status_code
    body_preview = ((response.text or "").strip())[:300]
    detail = f"{error_detail} (nexon HTTP {code})"
    if body_preview:
        detail = f"{detail}: {body_preview}"
    if code == 429:
        raise HTTPException(status_code=429, detail=detail)
    raise HTTPException(status_code=502, detail=detail)


def get_yesterday() -> str:
    """넥슨 캐릭터 API `date` 파라미터용 기준일(YYYY-MM-DD, KST).

    전일 스냅샷은 익일 오전 2시(KST)부터 조회 가능하므로, KST 02:00 미만이면
    이틀 전 날짜를, 그 이후면 어제 날짜를 반환한다.
    """
    now = datetime.now(KST)
    days_ago = 2 if now.hour < 2 else 1
    target = now.date() - timedelta(days=days_ago)
    return target.strftime("%Y-%m-%d")


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
        _raise_for_failed_nexon(response, error_detail)
    return response.json()


async def get_ocid(client: httpx.AsyncClient, nickname: str) -> str:
    """GET /maplestory/v1/id — 닉네임 → OCID"""
    response = await client.get(
        f"{BASE_URL}/id",
        headers=HEADERS,
        params={"character_name": nickname},
    )
    if response.status_code != 200:
        if response.status_code == 404:
            raise HTTPException(
                status_code=404,
                detail=f"'{nickname}' 캐릭터를 찾을 수 없습니다.",
            )
        _raise_for_failed_nexon(response, "캐릭터 ID 조회 실패")
    data = response.json()
    ocid = data.get("ocid")
    if not ocid:
        raise HTTPException(
            status_code=502,
            detail="넥슨 ID 응답에 ocid가 없습니다.",
        )
    return ocid


async def fetch_character_basic(client: httpx.AsyncClient, ocid: str, date: str):
    """GET /maplestory/v1/character/basic"""
    return await _fetch_ocid_date(
        client, "character/basic", ocid, date, "캐릭터 기본 정보 조회 실패"
    )


async def fetch_character_stat(client: httpx.AsyncClient, ocid: str, date: str):
    """GET /maplestory/v1/character/stat"""
    return await _fetch_ocid_date(
        client, "character/stat", ocid, date, "캐릭터 스탯 조회 실패"
    )


async def fetch_character_ability(client: httpx.AsyncClient, ocid: str, date: str):
    """GET /maplestory/v1/character/ability"""
    return await _fetch_ocid_date(
        client, "character/ability", ocid, date, "어빌리티 조회 실패"
    )


async def fetch_character_popularity(client: httpx.AsyncClient, ocid: str, date: str):
    """GET /maplestory/v1/character/popularity"""
    return await _fetch_ocid_date(
        client, "character/popularity", ocid, date, "캐릭터 인기도 조회 실패"
    )


async def fetch_union(client: httpx.AsyncClient, ocid: str, date: str):
    """GET /maplestory/v1/user/union — 레벨 등 (상세 탭 미구현 시에도 level만 사용)"""
    return await _fetch_ocid_date(
        client, "user/union", ocid, date, "유니온 정보 조회 실패"
    )


async def fetch_overall_ranking(client: httpx.AsyncClient, ocid: str, date: str):
    """GET /maplestory/v1/ranking/overall — 종합 랭킹"""
    return await _fetch_ocid_date(
        client, "ranking/overall", ocid, date, "종합 랭킹 조회 실패"
    )


async def fetch_item_equipment(client: httpx.AsyncClient, ocid: str, date: str):
    """GET /maplestory/v1/character/item-equipment"""
    return await _fetch_ocid_date(
        client, "character/item-equipment", ocid, date, "장비 정보 조회 실패"
    )

