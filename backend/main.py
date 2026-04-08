from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from routers.character import router as character_router

app = FastAPI(title="메이플스토리 캐릭터 검색 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 운영 시 특정 오리진으로 제한 권장
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(character_router)


@app.get("/")
def health_check():
    return {"status": "ok", "message": "메이플 캐릭터 검색 서버 정상 작동 중"}
