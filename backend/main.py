from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from routers import sunday
from routers.character import router as character_router
from routers.notice import router as notice_router

load_dotenv()

app = FastAPI(
    title="Sunday Maple API",
    description="썬데이 메이플 예측/이력·캐릭터 검색 API",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(character_router)
app.include_router(notice_router)
app.include_router(sunday.router)


@app.get("/")
def root():
    return {"status": "ok", "service": "Sunday Maple API"}


@app.get("/healthz")
def health_check():
    """Render 헬스체크 + 콜드스타트 방지용 ping."""
    return {"status": "healthy"}
