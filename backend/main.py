import asyncio
from datetime import datetime, timedelta

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os

# .env 파일에서 환경변수 읽기
load_dotenv()

app = FastAPI(title="메이플스토리 캐릭터 정보 API")

# CORS 설정 - 프론트엔드에서 백엔드를 호출할 수 있게 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
) 

# 넥슨 API 설정
API_KEY = os.getenv("NEXON_API_KEY")
BASE_URL = "https://open.api.nexon.com/maplestory/v1"
HEADERS = {"x-nxopen-api-key": API_KEY}


def get_yesterday() -> str:
    yesterday = datetime.now() - timedelta(days=2)
    return yesterday.strftime("%Y-%m-%d")


@app.get("/")
def health_check():
    return {"status": "ok", "message": "메이플 전적검색 서버 정상 작동 중"}


@app.get("/api/search")
async def search_character(nickname: str):
    if not API_KEY:
        raise HTTPException(status_code=500, detail="API 키가 설정되지 않았습니다.")

    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:

        # 1단계: 닉네임으로 OCID 조회
        ocid_response = await client.get(
            f"{BASE_URL}/id",
            headers=HEADERS,
            params={"character_name": nickname},
        )

        if ocid_response.status_code != 200:
            raise HTTPException(status_code=404, detail=f"'{nickname}' 캐릭터를 찾을 수 없습니다.")

        ocid = ocid_response.json()["ocid"]

        # 2단계: 기본 정보 + 스탯 동시 조회
        basic_task = client.get(
            f"{BASE_URL}/character/basic",
            headers=HEADERS,
            params={"ocid": ocid, "date": yesterday},
        )
        stat_task = client.get(
            f"{BASE_URL}/character/stat",
            headers=HEADERS,
            params={"ocid": ocid, "date": yesterday},
        )

        basic_response, stat_response = await asyncio.gather(basic_task, stat_task)

        if basic_response.status_code != 200:
            raise HTTPException(status_code=502, detail="캐릭터 기본 정보 조회 실패")
        if stat_response.status_code != 200:
            raise HTTPException(status_code=502, detail="캐릭터 스탯 조회 실패")

        basic = basic_response.json()
        stat = stat_response.json()

    # 3단계: 필요한 데이터만 정리해서 반환
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
# 엔드포인트 3: 장비 정보 조회
# ============================================================
@app.get("/api/equipment")
async def get_equipment(nickname: str):
    """
    닉네임으로 장착 중인 장비 정보를 조회한다.
    스타포스, 잠재능력, 추가옵션 등 상세 정보 포함.
    """

    if not API_KEY:
        raise HTTPException(status_code=500, detail="API 키가 설정되지 않았습니다.")

    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:

        # 1단계: OCID 조회
        ocid_response = await client.get(
            f"{BASE_URL}/id",
            headers=HEADERS,
            params={"character_name": nickname},
        )

        if ocid_response.status_code != 200:
            raise HTTPException(status_code=404, detail=f"'{nickname}' 캐릭터를 찾을 수 없습니다.")

        ocid = ocid_response.json()["ocid"]

        # 2단계: 장비 정보 조회
        equip_response = await client.get(
            f"{BASE_URL}/character/item-equipment",
            headers=HEADERS,
            params={"ocid": ocid, "date": yesterday},
        )

        if equip_response.status_code != 200:
            raise HTTPException(status_code=502, detail="장비 정보 조회 실패")

        equip_data = equip_response.json()

    # 3단계: 장비별 핵심 정보만 정리
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
# 엔드포인트 4: 유니온 정보 조회
# ============================================================
@app.get("/api/union")
async def get_union(nickname: str):
    """
    닉네임으로 유니온 레벨, 등급, 공격대 스탯을 조회한다.
    """

    if not API_KEY:
        raise HTTPException(status_code=500, detail="API 키가 설정되지 않았습니다.")

    yesterday = get_yesterday()

    async with httpx.AsyncClient(timeout=10.0) as client:

        # 1단계: OCID 조회
        ocid_response = await client.get(
            f"{BASE_URL}/id",
            headers=HEADERS,
            params={"character_name": nickname},
        )

        if ocid_response.status_code != 200:
            raise HTTPException(status_code=404, detail=f"'{nickname}' 캐릭터를 찾을 수 없습니다.")

        ocid = ocid_response.json()["ocid"]

        # 2단계: 유니온 기본 정보 + 공격대 정보 동시 조회
        union_task = client.get(
            f"{BASE_URL}/user/union",
            headers=HEADERS,
            params={"ocid": ocid, "date": yesterday},
        )
        raider_task = client.get(
            f"{BASE_URL}/user/union-raider",
            headers=HEADERS,
            params={"ocid": ocid, "date": yesterday},
        )

        union_response, raider_response = await asyncio.gather(union_task, raider_task)

        if union_response.status_code != 200:
            raise HTTPException(status_code=502, detail="유니온 정보 조회 실패")
        if raider_response.status_code != 200:
            raise HTTPException(status_code=502, detail="유니온 공격대 정보 조회 실패")

        union_data = union_response.json()
        raider_data = raider_response.json()

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