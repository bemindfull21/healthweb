# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@../_shared/CLAUDE.md

# health-web

체중 관리로 건강한 삶을 만드는 사람들의 커뮤니티. 몸무게 기록 + 피드/응원.
정적 프론트(GitHub Pages `bemindfull21/healthweb`, public) + VM FastAPI.

## Phase 1 (2026-09-09~) — 현재

"기록 → 공유 → 응원" 한 루프. 인증은 아이디/비밀번호, 몸무게는 웹앱 입력만(**텔레그램 봇 입력 폐기**).

### 프론트

| 파일 | 역할 |
|---|---|
| `index.html` + `landing.js` + `config.js` | 공개 랜딩 — 로그인/회원가입/비번재설정 + 다이어트 철학 글. 바닐라 JS |
| `app.html` + `app.js` | 로그인 후 **SPA 셸** — Preact + htm (esm.sh, **빌드 없음**), history 라우팅 |
| `404.html` | GH Pages 딥링크 폴백 (원 경로 sessionStorage → `app.html` → `app.js`가 복원) |
| `style.css` | 공통 |

- 로그인/가입 → JWT를 `localStorage["healthweb.token"]` → `app.html`. `401` → 토큰 삭제 후 랜딩.
- 라우트: `/feed`(전역 피드) · `/me`(차트·표·입력) · `/p/:id`(글 상세) · `/u/:handle`(프로필) · `/settings`.
- 탭바 P1은 **피드 · ＋ · 나** 3개. ＋ = 액션 시트(몸무게 기록 / 글쓰기).
- `app.js`의 `const API` + `config.js`의 `window.HW.API` 를 로컬 테스트 시 `http://localhost:8971`로 바꿔서 검증.

### API (`api/app.py`)

아이디(`^[a-z0-9]{3,20}$`, 소문자 정규화) / 비밀번호. JWT `sub` = username.

| 그룹 | 엔드포인트 |
|---|---|
| 인증 | `GET /auth/username-available` · `POST /auth/signup` (username·user_name·password·target_weight) · `/auth/signin` · `/auth/reset` (username + **user_name 일치**로 재설정) · `GET /auth/me` · `PATCH /auth/me` |
| 몸무게 | `GET/POST /weights` · `DELETE /weights/:id` (연결 글은 링크만 끊음) |
| 커뮤니티 | `GET /feed?cursor=` · `POST /posts` · `GET /posts/:id` · `POST/DELETE /posts/:id/encourage` · `POST /posts/:id/comments` · `DELETE /posts/:id` · `GET /u/:handle` |

- bcrypt · PyJWT(HS256, 7일). `user_name`은 비공개(재설정 확인용), 공개 handle = username.
- `weight_privacy`(`private`/`trend`/`public`): 프로필의 몸무게 노출 + `log` 글의 weight 표시 여부(`public`만).
- 코드/시각: `parse_dt`는 사용자 벽시계 시각 그대로 저장(naive). `iso_z` 응답.
- 전역 `@app.exception_handler(Exception)` → `{"detail": ...}` JSON 500.

### DB (`healthweb` 스키마)

`sql/010_phase1_schema.sql` (**적용됨** — ADMIN으로 실행, `grant create sequence` 포함):
`app_user`(username PK · user_name · password_hash · bio · target_weight · weight_privacy) ·
`weight_entry`(username · logged_at · weight · note) ·
`post`(username · kind · body · weight_entry_id) · `encouragement`(PK post_id+username) · `post_comment`.
`verify_code` · 구 `app_user`(email/tg) drop됨.

`sql/011_migrate_owner_weights.sql` — 오너가 가입 후 `<USERNAME>` 바꿔 실행 (구 텔레그램 이력 → weight_entry).

## VM 배포 (memo-agent)

- `/opt/health-web-api/` : `healthweb-api.service`(uvicorn :8000) + `caddy.service`(`healthweb21.duckdns.org`).
- `.env`: DB 자격증명 + `JWT_SECRET` + `ALLOW_ORIGIN=https://bemindfull21.github.io`. (`INTERNAL_KEY`는 Phase 1에서 미사용)
- 재배포: `scp api/app.py opc@168.107.89.8:/opt/health-web-api/ && ssh ... 'sudo systemctl restart healthweb-api'`.

## 폐기됨

- **텔레그램 봇 몸무게 입력** — `health-bot`의 `handle_message` 저장 로직 · `save_to_db` · `/link` · `/reset` 핸들러. 봇 완전 은퇴는 미결.
- **배치 ETL** — `refresh-data.yml` · `scripts/` · `data/users/*.json`. Phase 1은 API 직결만(정적 폴백 없음).
- 이메일 인증, 텔레그램 검증(`verify_code`), `dashboard.js`(→ `app.js`로 흡수).

## 미완 (Phase 2+)

챌린지 · 팔로우 · 알림 탭 · 그룹 · 검색 · 사진(오브젝트 스토리지) · 리치 프로필.
설계: 커뮤니티 IA / Phase 1 상세 설계 아트팩트 (메모리 참조).
