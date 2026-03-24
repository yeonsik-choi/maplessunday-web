# 프론트엔드 연동 가이드

Vercel 등 **별도 도메인**에서 호출할 때 기준으로 정리했습니다.

## Base URL

| 환경 | URL |
|------|-----|
| 프로덕션 | `https://openapi-web-project.onrender.com` |
| 로컬 | `http://127.0.0.1:8000` |

Vercel 환경 변수 (Next.js 예시):

```
NEXT_PUBLIC_API_BASE_URL=https://openapi-web-project.onrender.com
```

Vite를 쓰면 `VITE_API_BASE_URL` 로 두고, 아래 코드에서 `import.meta.env.VITE_API_BASE_URL` 을 사용하세요.

코드에서 `` `${BASE}/api/...` `` 로 조합합니다.

## 문서

| 설명 | URL |
|------|-----|
| Swagger UI | `https://openapi-web-project.onrender.com/docs` |
| OpenAPI JSON | `https://openapi-web-project.onrender.com/openapi.json` |

`GET /api/all` 응답은 스키마 **`CharacterAllResponse`**에 **Example Value**가 붙어 있어, `/docs`에서 구조를 바로 볼 수 있습니다.

---

## 캐릭터 API

공통 쿼리: **`nickname`** (검색할 캐릭터 닉네임)

넥슨 API 키는 **백엔드에서만** 사용합니다. **프론트 코드에 키를 넣지 마세요.**

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/all` | **정보창용 통합** (한 번에 대부분의 필드) |
| GET | `/api/search` | 기본 + 주요 스탯 + 인기도/랭킹 |
| GET | `/api/popularity` | 인기도만 |
| GET | `/api/ranking-overall` | 종합 랭킹 순위만 |
| GET | `/api/equipment` | 장비 목록 |
| GET | `/api/union` | 유니온 + 공격대 |
| GET | `/api/hyper-stat` | 하이퍼 스탯 |
| GET | `/api/symbol` | 심볼 (성장 카운트 포함) |
| GET | `/api/ability` | 어빌리티 |
| GET | `/api/set-effect` | 세트 효과 |
| GET | `/api/link-skill` | 링크 스킬 |
| GET | `/api/hexamatrix` | 헥사 코어 |
| GET | `/api/hexamatrix-stat` | 헥사 스탯 코어 |

대부분의 경우 **`/api/all` 하나면 충분**합니다. 특정 정보만 가볍게 필요할 때 보조 엔드포인트를 사용하세요.

### 호출 예시

```ts
// Next.js (클라이언트 컴포넌트)
const base = process.env.NEXT_PUBLIC_API_BASE_URL;

// Vite
// const base = import.meta.env.VITE_API_BASE_URL;

const res = await fetch(`${base}/api/all?nickname=${encodeURIComponent(nick)}`);
const data = await res.json();
if (!res.ok) {
  // 아래 "에러 응답" 참고
}
```

### 응답 필드 참고 (`GET /api/all`)

- **`symbols.list`**: JSON 키 이름이 `list`입니다 (배열).
- **`overall_rank`**: 넥슨 랭킹 API 특성상 `null`일 수 있습니다.
- 일부 블록(`set_effect`, `link_skill`, 헥사 등)은 넥슨 원본 구조가 그대로 내려옵니다. 상세는 `/docs` 스키마를 참고하세요.

정보창 UI 항목(이미지·닉·서버·직업·길드·랭킹·인기도·레벨·유니온·전투력·장비·심볼)과 JSON 필드 매핑은 `schemas/character_all.py` 모듈 상단 주석을 참고하세요.

---

## 에러 응답

### 애플리케이션 에러 (`HTTPException`)

```json
{ "detail": "사람이 읽을 수 있는 메시지 문자열" }
```

| 코드 | 대표 상황 | 예시 `detail` |
|------|-----------|----------------|
| 404 | 캐릭터 없음 | `'닉네임' 캐릭터를 찾을 수 없습니다.` |
| 500 | API 키 미설정 | `API 키가 설정되지 않았습니다.` |
| 502 | 넥슨 API 호출 실패 | `캐릭터 기본 정보 조회 실패` |

`nickname` 쿼리 누락 등은 **422**로 올 수 있습니다 (아래 참고).

### 요청 검증 에러 (422)

쿼리/바디 타입이 잘못된 경우 **`detail`이 배열**로 옵니다.

```json
{
  "detail": [
    {
      "type": "int_parsing",
      "loc": ["query", "n"],
      "msg": "Input should be a valid integer",
      "input": "x"
    }
  ]
}
```

프론트에서 두 형태를 모두 처리하려면:

```ts
function formatErrorDetail(data: { detail: unknown }): string {
  const d = data.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d[0]?.msg) return d.map((e) => e.msg).join("; ");
  return "요청 오류";
}
```

---

## CORS

현재 `allow_origins=["*"]`로 전 출처 허용 중입니다. 프로덕션에서 좁히려면 백엔드 담당자에게 배포된 Vercel 도메인을 공유해 주세요.

---

## 주의사항

- Render 무료 플랜 사용 중 → **첫 요청 30초~1분 소요 가능** (슬립 모드)
- 헬스 체크: `GET /` 으로 서버 상태 확인 가능

---

## 참고 링크

- [넥슨 오픈 API](https://openapi.nexon.com/game/maplestory)
- [FastAPI CORS 문서](https://fastapi.tiangolo.com/tutorial/cors/)
- [백엔드 레포 (GitHub)](https://github.com/yeonsik-choi/Openapi-web-project)
