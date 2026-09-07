# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@../_shared/CLAUDE.md

# health-web

health-bot이 SHINDB `weight_log`에 저장한 몸무게를 조회하는 웹앱.
정적 프론트(GitHub Pages, public repo) + VM의 인증/조회 API(FastAPI).

## 2페이지 구조

| 페이지 | 내용 |
|---|---|
| `index.html` + `landing.js` | 랜딩 — 로그인 / 회원가입 / 비밀번호 재설정 폼 + 다이어트 철학 글 |
| `app.html` + `dashboard.js` | 대시보드 — 통계·차트·표. 토큰 없으면 `index.html`로 리다이렉트 |
| `config.js` | 공통 (`API` URL, `TOKEN_KEY`, `ME_KEY`). **빌드 없음** — 여기만 바꾸면 됨 |
| `style.css` | 공통 |

- 로그인/가입 성공 → JWT를 `localStorage["healthweb.token"]` 저장 → `app.html`.
- `app.html` 진입 → `GET /auth/me` (Bearer). 미인증이면 `/link` 코드 게이트, 인증이면 `GET /weights` → 렌더.
- `401` 응답 → 토큰 삭제 후 랜딩으로. API 다운 → 캐시된 `me` + 정적 스냅샷 폴백 + `#staleness` 표시.

## 인증 (`api/app.py`)

email/password 계정. 텔레그램 소유권은 봇으로 검증(**결정 1-B**).

| 엔드포인트 | 설명 |
|---|---|
| `POST /auth/signup` | email·pw(8+)·tg_user_id(+목표) → `app_user`(verified=N) + `/link` 코드 → JWT |
| `POST /auth/signin` | email·pw → JWT. 레이트리밋: email 5회/15분 + IP 15회/분 |
| `POST /auth/reset` | email·새 pw → `verify_code`에 새 해시 저장 + `/reset` 코드 (봇 확인 후 반영) |
| `GET /auth/me` | Bearer → 계정 정보. 미인증이면 활성 `link_code` 포함 |
| `GET /weights` | Bearer(+verified) → **토큰의 tg_user_id**로 `admin.weight_log` 조회 (`?uid=` 없음) |
| `POST /internal/link` | health-bot 전용(`X-Internal-Key`) — `verify_code` 대조 → `verified=Y` |
| `POST /internal/reset` | health-bot 전용 — `verify_code` 대조 → `password_hash` 교체 |

- bcrypt 해시, JWT(HS256, 7일). `.env`에 `JWT_SECRET`·`INTERNAL_KEY` (openssl rand로 각각 생성, 공유 비번 재사용 금지).
- `/internal/*` 은 Caddy에서 외부 404 (`@internal path /internal/*` → `respond 404`). health-bot은 `http://127.0.0.1:8000` 직접 호출.
- 코드 만료(10분) 비교는 **naive UTC 바인드**(`code_cutoff()`) — `systimestamp`를 WHERE에 쓰면 python-oracledb 세션 TZ로 암묵 변환돼 어긋난다(ADB server=UTC).

### health-bot 연동

health-bot `main.py`에 `/link <코드>` `/reset <코드>` 명령. 6자리 코드 + `str(update.effective_user.id)`를
`/internal/*`에 POST. `INTERNAL_KEY` env 필요 (`/opt/health-bot/.env` = `/opt/health-web-api/.env` 와 동일 값).

## DB (SHINDB, `healthweb` 유저)

`healthweb` — `grant connect`, `grant select on admin.weight_log`, `grant create table` + quota 50m.

| 객체 | 용도 | SQL |
|---|---|---|
| `admin.weight_log` | 몸무게 원천 (읽기만) | — |
| `healthweb.app_user` | 웹 계정 (email·hash·tg_user_id·verified·target_weight) | `sql/002_app_user.sql` |
| `healthweb.verify_code` | link/reset 코드 (purpose·email·tg_user_id·new_hash·consumed) | `sql/003_verify_code.sql` |

wallet은 [[healthbot-autonomous-db]]와 동일(공용 `_shared/wallets/SHINDB`). Actions엔 `WALLET_ZIP_B64` Secret.

## 두 조회 경로 (배치 폴백 + 실시간)

```
[배치·폴백]  weight_log ──(매일 1회 UTC18 / 수동 / repository_dispatch)──▶ scripts/export_weights.py
             ──▶ data/users/<sha256(tg_user_id)>.json 커밋 ──▶ Pages
[실시간]     weight_log ──▶ VM: Caddy(healthweb21.duckdns.org) → uvicorn:8000 ──▶ GET /weights
```

- **배치의 역할**: 최신성 아님 — VM 다운 시 폴백 + 방문/스캐너 트래픽이 DB로 안 가게. 하루 1회면 충분.
- 대시보드는 **실시간 우선**. `GET /weights` 실패 시 `fetchStatic(tg_user_id)` → `data/users/<hash>.json`.
  성공하면 `#staleness` 지속 표시("실시간 연결 안 됨 · 마지막 갱신 N시간 전 · [다시 시도]"), 429는 제외.
- `scripts/export_weights.py` 쿼리 = API의 `WEIGHT_QUERY` 와 동일 컬럼·조건. 응답 형태도 동일:
  `{updated_at, count, entries:[{date,time,weight,quote}]}`.

## VM 배포 (memo-agent, Oracle Linux 9.8, Singapore)

- 소스 `/opt/health-web-api/` (app.py·venv·`.env` chmod 600·`duck/`).
- **`healthweb-api.service`** — `uvicorn app:app --host 127.0.0.1 --port 8000`.
- **`caddy.service`** — `/etc/caddy/Caddyfile`. LE 인증서 tls-alpn-01 자동.
- 방화벽: OCI Security List 80·443 + firewalld `http`/`https`.
- DuckDNS: `healthweb21` → 공용 IP(ephemeral 유지). 갱신 `/opt/health-web-api/duck/duck.sh` + cron `*/5`.
- **재배포**: `scp api/app.py opc@168.107.89.8:/opt/health-web-api/ && ssh ... 'sudo systemctl restart healthweb-api'`.
  Caddyfile 바꾸면 `sudo cp` 후 `sudo systemctl reload caddy`. deps 바뀌면 `./venv/bin/pip install -r requirements.txt`.
- health-bot 재배포: `scp main.py opc@...:/opt/health-bot/ && ssh ... 'sudo systemctl restart healthbot'`
  (모듈 로드 시 gspread 초기화라 Google 503이면 첫 기동 실패 → systemd가 재시작해 성공).

## (선택) 미완

- 대시보드를 켜둔 채로는 자동 갱신 안 됨(폴링/SSE 없음) — 열 때만 당겨옴.
- 봇 `repository_dispatch` 미연결 — 폴백 스냅샷 조기 갱신용, 우선순위 낮음.
- 이메일 인증 메일 없음(email = 사실상 아이디). 비번 재설정은 봇 경유.
