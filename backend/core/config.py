import os
from dotenv import load_dotenv

load_dotenv()

# 넥슨 API 설정
NEXON_API_KEY = os.getenv("NEXON_API_KEY")
# True면 HTTP_PROXY/HTTPS_PROXY 사용. 프록시가 넥슨을 막으면 false 유지(기본).
NEXON_HTTP_TRUST_ENV = os.getenv("NEXON_HTTP_TRUST_ENV", "").strip().lower() in (
    "1",
    "true",
    "yes",
)
BASE_URL = "https://open.api.nexon.com/maplestory/v1"
HEADERS = {"x-nxopen-api-key": NEXON_API_KEY}
