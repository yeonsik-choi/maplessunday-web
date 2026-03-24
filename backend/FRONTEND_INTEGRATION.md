# 프론트엔드 연동 가이드 (캐릭터 API)

Vercel 등 **별도 도메인**에서 호출할 때 기준입니다.

## Base URL

배포된 FastAPI 서버 루트 (예: `https://api.example.com`). 로컬: `http://127.0.0.1:8000`

환경 변수 예: `VITE_API_BASE_URL` / `NEXT_PUBLIC_API_BASE_URL` → `` `${BASE}/api/...` `` 로 조합.

## 문서

| 설명 | URL |
|------|-----|
| Swagger UI | `{Base URL}/docs` |
| OpenAPI JSON | `{Base URL}/openapi.json` |

`GET /api/all` 응답 스키마 **`CharacterAllResponse`**에 **Example Value**가 있어 `/docs`에서 샘플 JSON을 바로 볼 수 있습니다.  
필드와 화면 항목 대응은 아래 표와 `schemas/character_all.py` 모듈 상단 주석을 참고하세요.

---

## 정보창 항목 → `GET /api/all` JSON 필드

| 화면에서 보여줄 항목 | 응답 필드 (경로) | 비고 |
|---------------------|------------------|------|
| 캐릭터 이미지 | `character_image` | URL 문자열 |
| 닉네임 | `character_name` | |
| 서버 | `world_name` | |
| 직업 | `character_class` | |
| 길드 | `character_guild_name` | 없으면 null |
| 랭킹 | `overall_rank` | 없을 수 있음(null). 기준일 `ranking_date` |
| 인기도 | `popularity` | 기준일 `popularity_date` |
| 레벨 | `character_level` | |
| 유니온 | `union` | `union_level`, `union_grade`, `union_artifact_level`, 공격대 등 |
| 전투력 | `combat_power` | 문자열로 오는 경우 많음 |
| 장비 | `equipment.items` | 각 요소: `slot`, `name`, `icon`, 잠재·스타포스 등 |
| 심볼 | `symbols.list` | **키 이름이 `list`** 인 배열 |

요청: **`GET /api/all?nickname=닉네임`**  
서버에 **`NEXON_API_KEY`** 필요. **키는 프론트에 넣지 않음.**

추가로 같은 응답에 `main_stats`, `hyper_stat`, `ability`, `set_effect`, `link_skill`, 헥사 등이 포함될 수 있습니다. 상세는 `/docs`의 `CharacterAllResponse` 참고.

---

## 기타 캐릭터 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | `/api/search` | 기본 + 주요 스탯 + 인기도/랭킹(가능 시) |
| GET | `/api/popularity` | 인기도만 |
| GET | `/api/ranking-overall` | 종합 랭킹만 |
| GET | `/api/equipment` | 장비만 |
| GET | `/api/union` | 유니온만 |
| GET | `/api/hyper-stat` | 하이퍼 스탯 |
| GET | `/api/symbol` | 심볼만 (`/api/all`보다 성장 필드 등이 더 있을 수 있음) |
| GET | `/api/ability` | 어빌리티 |
| GET | `/api/set-effect` | 세트 효과 |
| GET | `/api/link-skill` | 링크 스킬 |
| GET | `/api/hexamatrix` | 헥사 코어 |
| GET | `/api/hexamatrix-stat` | 헥사 스탯 코어 |

### 호출 예시

```http
GET /api/all?nickname=캐릭터닉네임
```

```ts
const base = import.meta.env.VITE_API_BASE_URL;
const res = await fetch(`${base}/api/all?nickname=${encodeURIComponent(nick)}`);
const data = await res.json();
if (!res.ok) {
  // 아래 "에러 응답" 참고
}
```

---

## 에러 응답

### 애플리케이션 에러 (`HTTPException`)

캐릭터 API는 **`HTTPException`** 사용 → 기본 형태:

```json
{ "detail": "사람이 읽을 수 있는 메시지 문자열" }
```

| 코드 | 대표 상황 | 예시 `detail` |
|------|-----------|----------------|
| 404 | 캐릭터 없음 | `'닉네임' 캐릭터를 찾을 수 없습니다.` |
| 500 | `NEXON_API_KEY` 미설정 | `API 키가 설정되지 않았습니다.` |
| 502 | 넥슨 API 실패 | `캐릭터 기본 정보 조회 실패` 등 |

`res.ok`가 아니면 `await res.json()` 후 **`data.detail`**(문자열)을 표시하면 됩니다.

### 요청 검증 에러 (422)

쿼리 타입 오류 시 **`detail`이 배열**입니다.

```json
{
  "detail": [
    {
      "type": "int_parsing",
      "loc": ["query", "n"],
      "msg": "Input should be a valid integer, unable to parse string as an integer",
      "input": "x"
    }
  ]
}
```

권장 처리:

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

현재 `allow_origins=["*"]` 이라 Vercel 등에서 호출 가능. 운영 시 프론트 도메인만 허용하도록 좁힐 수 있습니다.

---

## 참고 링크

- [넥슨 오픈 API](https://openapi.nexon.com/game/maplestory)
- [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)
