from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from fastapi import HTTPException

from core.config import BASE_URL, HEADERS, NEXON_API_KEY

KST = ZoneInfo("Asia/Seoul")


def require_nexon_api_key() -> None:
    if not NEXON_API_KEY:
        raise HTTPException(status_code=500, detail="API 키가 설정되지 않았습니다.")


def raise_nexon_request_error(exc: httpx.RequestError) -> None:
    raise HTTPException(
        status_code=502,
        detail=(
            "넥슨 오픈 API에 연결하지 못했습니다. "
            f"({type(exc).__name__}: {exc}) "
            "VPN·회사 프록시·HTTP_PROXY 환경이면 비활성화 후 다시 시도하거나, "
            "방화벽에서 open.api.nexon.com 허용을 확인하세요."
        ),
    ) from exc


def _raise_for_failed_nexon(response: httpx.Response, error_detail: str) -> None:
    code = response.status_code
    body_preview = ((response.text or "").strip())[:300]
    detail = f"{error_detail} (nexon HTTP {code})"
    if body_preview:
        detail = f"{detail}: {body_preview}"
    if code == 429:
        raise HTTPException(status_code=429, detail=detail)
    raise HTTPException(status_code=502, detail=detail)


async def _get_json(
    client: httpx.AsyncClient,
    path: str,
    params: dict[str, str],
    error_detail: str,
    *,
    not_found_detail: str | None = None,
) -> dict:
    response = await client.get(
        f"{BASE_URL}/{path}",
        headers=HEADERS,
        params=params,
    )
    if response.status_code != 200:
        if not_found_detail is not None and response.status_code == 404:
            raise HTTPException(status_code=404, detail=not_found_detail)
        _raise_for_failed_nexon(response, error_detail)
    return response.json()


def get_yesterday() -> str:
    now = datetime.now(KST)
    days_ago = 2 if now.hour < 2 else 1
    target = now.date() - timedelta(days=days_ago)
    return target.strftime("%Y-%m-%d")


async def get_ocid(client: httpx.AsyncClient, nickname: str) -> str:
    data = await _get_json(
        client,
        "id",
        {"character_name": nickname},
        "캐릭터 ID 조회 실패",
        not_found_detail=f"'{nickname}' 캐릭터를 찾을 수 없습니다.",
    )
    ocid = data.get("ocid")
    if not ocid:
        raise HTTPException(status_code=502, detail="넥슨 ID 응답에 ocid가 없습니다.")
    return ocid


async def _fetch_ocid_date(
    client: httpx.AsyncClient,
    subpath: str,
    ocid: str,
    date: str,
    error_detail: str,
) -> dict:
    return await _get_json(
        client,
        subpath,
        {"ocid": ocid, "date": date},
        error_detail,
    )


async def fetch_character_skill(
    client: httpx.AsyncClient, ocid: str, date: str, character_skill_grade: str
) -> dict:
    return await _get_json(
        client,
        "character/skill",
        {
            "ocid": ocid,
            "date": date,
            "character_skill_grade": character_skill_grade,
        },
        f"캐릭터 스킬 조회 실패 (grade={character_skill_grade})",
    )


async def fetch_character_basic(
    client: httpx.AsyncClient, ocid: str, date: str
) -> dict:
    return await _fetch_ocid_date(
        client, "character/basic", ocid, date, "캐릭터 기본 정보 조회 실패"
    )


async def fetch_character_stat(client: httpx.AsyncClient, ocid: str, date: str) -> dict:
    return await _fetch_ocid_date(
        client, "character/stat", ocid, date, "캐릭터 스탯 조회 실패"
    )


async def fetch_character_ability(
    client: httpx.AsyncClient, ocid: str, date: str
) -> dict:
    return await _fetch_ocid_date(
        client, "character/ability", ocid, date, "어빌리티 조회 실패"
    )


async def fetch_character_popularity(
    client: httpx.AsyncClient, ocid: str, date: str
) -> dict:
    return await _fetch_ocid_date(
        client, "character/popularity", ocid, date, "캐릭터 인기도 조회 실패"
    )


async def fetch_union(client: httpx.AsyncClient, ocid: str, date: str) -> dict:
    return await _fetch_ocid_date(
        client, "user/union", ocid, date, "유니온 정보 조회 실패"
    )


async def fetch_union_raider(
    client: httpx.AsyncClient, ocid: str, date: str
) -> dict:
    return await _fetch_ocid_date(
        client, "user/union-raider", ocid, date, "유니온 공격대 정보 조회 실패"
    )


async def fetch_union_artifact(
    client: httpx.AsyncClient, ocid: str, date: str
) -> dict:
    return await _fetch_ocid_date(
        client, "user/union-artifact", ocid, date, "유니온 아티팩트 정보 조회 실패"
    )


async def fetch_union_champion(
    client: httpx.AsyncClient, ocid: str, date: str
) -> dict:
    return await _fetch_ocid_date(
        client, "user/union-champion", ocid, date, "유니온 챔피언 정보 조회 실패"
    )


async def fetch_overall_ranking(
    client: httpx.AsyncClient, ocid: str, date: str
) -> dict:
    return await _fetch_ocid_date(
        client, "ranking/overall", ocid, date, "종합 랭킹 조회 실패"
    )


async def fetch_item_equipment(
    client: httpx.AsyncClient, ocid: str, date: str
) -> dict:
    return await _fetch_ocid_date(
        client, "character/item-equipment", ocid, date, "장비 정보 조회 실패"
    )


async def fetch_set_effect(
    client: httpx.AsyncClient, ocid: str, date: str
) -> dict:
    return await _fetch_ocid_date(
        client, "character/set-effect", ocid, date, "세트효과 조회 실패"
    )


async def fetch_notice_list(client: httpx.AsyncClient) -> dict:
    return await _get_json(client, "notice", {}, "공지 목록 조회 실패")


async def fetch_notice_update_list(client: httpx.AsyncClient) -> dict:
    return await _get_json(client, "notice-update", {}, "업데이트 공지 목록 조회 실패")


async def fetch_notice_event_list(client: httpx.AsyncClient) -> dict:
    return await _get_json(client, "notice-event", {}, "이벤트 공지 목록 조회 실패")


async def fetch_notice_cashshop_list(client: httpx.AsyncClient) -> dict:
    return await _get_json(client, "notice-cashshop", {}, "캐시샵 공지 목록 조회 실패")
