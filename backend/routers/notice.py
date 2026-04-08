import asyncio
import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException

from core.config import NEXON_API_KEY, NEXON_HTTP_TRUST_ENV
from schemas.notice import (
    CashshopNoticeItem,
    EventNoticeItem,
    NoticeLinkItem,
    NoticesResponse,
)
from services.nexon_api import (
    fetch_notice_cashshop_list,
    fetch_notice_event_list,
    fetch_notice_list,
    fetch_notice_update_list,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["공지"])

_NEXON_TIMEOUT_SEC = 30.0
_FETCH_NAMES = ("notice", "notice_update", "notice_event", "notice_cashshop")


def _require_key() -> None:
    if not NEXON_API_KEY:
        raise HTTPException(status_code=500, detail="API 키가 설정되지 않았습니다.")


def _nget(d: dict | None, *keys: str) -> Any:
    if not d:
        return None
    for k in keys:
        v = d.get(k)
        if v is not None:
            return v
    return None


def _str_field(v: Any) -> str:
    if v is None:
        return ""
    return str(v).strip()


def _first_list(d: dict | None, *keys: str) -> list:
    if not d:
        return []
    for k in keys:
        v = d.get(k)
        if isinstance(v, list):
            return v
    return []


def _link_items(rows: list) -> list[NoticeLinkItem]:
    out: list[NoticeLinkItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            NoticeLinkItem(
                title=_str_field(_nget(row, "title")),
                url=_str_field(_nget(row, "url")),
                date=_str_field(_nget(row, "date")),
            )
        )
    return out


def _event_items(rows: list) -> list[EventNoticeItem]:
    out: list[EventNoticeItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            EventNoticeItem(
                title=_str_field(_nget(row, "title")),
                url=_str_field(_nget(row, "url")),
                thumbnailUrl=_str_field(
                    _nget(row, "thumbnail_url", "thumbnailUrl")
                ),
                startDate=_str_field(
                    _nget(row, "date_event_start", "dateEventStart")
                ),
                endDate=_str_field(
                    _nget(row, "date_event_end", "dateEventEnd")
                ),
            )
        )
    return out


def _ongoing_bool(raw: Any) -> bool:
    if raw is True:
        return True
    if raw is False or raw is None:
        return False
    s = str(raw).strip().lower()
    return s in ("true", "1", "yes", "y")


def _cashshop_items(rows: list) -> list[CashshopNoticeItem]:
    out: list[CashshopNoticeItem] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        out.append(
            CashshopNoticeItem(
                title=_str_field(_nget(row, "title")),
                url=_str_field(_nget(row, "url")),
                thumbnailUrl=_str_field(
                    _nget(row, "thumbnail_url", "thumbnailUrl")
                ),
                startDate=_str_field(
                    _nget(row, "date_sale_start", "dateSaleStart")
                ),
                endDate=_str_field(
                    _nget(row, "date_sale_end", "dateSaleEnd")
                ),
                ongoing=_ongoing_bool(
                    _nget(row, "ongoing_flag", "ongoingFlag")
                ),
            )
        )
    return out


def _pick_result(results: list, index: int) -> dict:
    if index >= len(results):
        return {}
    r = results[index]
    return r if isinstance(r, dict) else {}


@router.get(
    "/notices",
    response_model=NoticesResponse,
    responses={
        429: {"description": "넥슨 API rate limit"},
        502: {"description": "넥슨 API HTTP 오류 또는 네트워크/프록시 연결 실패"},
    },
)
async def get_notices():
    _require_key()
    try:
        async with httpx.AsyncClient(
            timeout=_NEXON_TIMEOUT_SEC,
            trust_env=NEXON_HTTP_TRUST_ENV,
        ) as client:
            results = await asyncio.gather(
                fetch_notice_list(client),
                fetch_notice_update_list(client),
                fetch_notice_event_list(client),
                fetch_notice_cashshop_list(client),
                return_exceptions=True,
            )
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
            name = _FETCH_NAMES[i] if i < len(_FETCH_NAMES) else str(i)
            logger.warning("nexon notice fetch failed %s: %s", name, r)

    notice_raw = _pick_result(results, 0)
    update_raw = _pick_result(results, 1)
    event_raw = _pick_result(results, 2)
    cash_raw = _pick_result(results, 3)

    notice_rows = _first_list(notice_raw, "notice")
    update_rows = _first_list(
        update_raw, "update_notice", "updateNotice"
    )
    event_rows = _first_list(
        event_raw, "event_notice", "eventNotice"
    )
    cash_rows = _first_list(
        cash_raw, "cashshop_notice", "cashshopNotice"
    )

    return NoticesResponse(
        notice=_link_items(notice_rows),
        update=_link_items(update_rows),
        event=_event_items(event_rows),
        cashshop=_cashshop_items(cash_rows),
    )
