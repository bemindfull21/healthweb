# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

@../_shared/CLAUDE.md

# health-web

서비스명 **마이웨이트, 마이러브 (MyWeight, MyLove)** — 2026-09-11 확정 (구 "자기사랑 연습"). 엠블럼은 "결의 하트"
(보석처럼 깎인 하트, `favicon.svg`). 이름은 랜딩 히어로·브라우저 탭·소개 페이지 하단 서명에만 노출("문 앞에서만").
자기이해·자기수용·자기돌봄(자기사랑)을 습관으로 만들어가는 사람들의 커뮤니티. 몸무게 기록은 자기돌봄의 상징 + 피드/응원.
정적 프론트(GitHub Pages `bemindfull21/healthweb`, public) + VM FastAPI.

## Phase 1·2 (2026-09-09) — 현재

"기록 → 공유 → 응원" 한 루프. 인증은 아이디/비밀번호, 몸무게는 웹앱 입력만(**텔레그램 봇 입력 폐기**).

### 프론트

| 파일 | 역할 |
|---|---|
| `index.html` + `landing.js` + `config.js` | 공개 랜딩 — 로그인/회원가입/비번재설정 + 다이어트 철학 글. 바닐라 JS |
| `app.html` + `app.js` | 로그인 후 **SPA 셸** — Preact + htm (esm.sh, **빌드 없음**), history 라우팅 |
| `404.html` | GH Pages 딥링크 폴백 (원 경로 sessionStorage → `app.html` → `app.js`가 복원) |
| `style.css` | 공통 |

- 로그인/가입 → JWT를 `localStorage["healthweb.token"]` → `app.html`. `401` → 토큰 삭제 후 랜딩.
- 라우트: `/feed` · `/challenges`·`/challenges/:id` · `/notifications` · `/me` · `/search` · `/p/:id` · `/u/:handle` · `/settings` · `/admin`(오너 허브)·`/admin/reports`·`/admin/announcements`.
  공개(로그인 불필요): `about.html` · `challenge.html?id=`.
- 탭바 5개: 피드 · 챌린지 · ＋ · 알림 · 나. ＋ = 액션 시트(몸무게 기록 / 글쓰기 / 챌린지 만들기).
- **브랜드**: `favicon.svg`(결의 하트, 고정 hex — CSS 변수 미사용) 전 페이지 `<link rel="icon">`. `--love`(rose, style.css 라이트/다크)
  + 기존 `--accent`(green) 두 색으로 "마이웨이트"/"마이러브" 분리 표기. `.wordmark`(랜딩 히어로, Gowun Batang·Fraunces 구글 폰트)
  · `.brand-sig`(소개 페이지 하단 서명, 작은 하트+이름). in-app 화면엔 로고 반복 안 함("문 앞에서만" 원칙).
- **홈 화면 아이콘**: `icon-512.png`/`icon-192.png`/`apple-touch-icon.png` — 초록/로즈 대각 분할 + 흰 M, `scripts/make_icons.py`(Pillow,
  폰트 없이 폴리라인으로 M 그림)로 생성 — 색·모양 바꾸면 `api/venv/Scripts/python.exe scripts/make_icons.py` 재실행.
  `manifest.json`(`display:standalone`) + 4개 HTML 전부에 `apple-touch-icon`·`manifest`·`theme-color` 링크.
- 로컬 테스트: `app.js`의 `const API` + `config.js`의 `window.HW.API` 를 `http://127.0.0.1:8971`로 `sed` (테스트 후 `git checkout config.js` + 역치환). 정적은 `python -m http.server 8080`.
  `scratchpad/`에 `test_p1~p3b.py`(전부 통과) · `runserver.sh`(MEDIA env 포함) · `e2e_*.py`(브라우저 데모 데이터, `--clean`). signup 레이트리밋 5/시간이라 스위트마다 서버 재시작.

### API (`api/app.py`)

**로그인 아이디**(`login_id`, `^[a-z0-9]{3,20}$` 소문자, **비공개**) / 비밀번호.
**이름**(`name`)이 공개 handle — 피드·프로필·`/u/:name` URL. 둘 다 unique. JWT `sub` = login_id.

| 그룹 | 엔드포인트 |
|---|---|
| 인증 | `GET /auth/check?login_id=&name=` (둘 다 중복확인) · `POST /auth/signup` (login_id·name·password·target_weight) · `/auth/signin` · `/auth/reset` (login_id + **name 일치**) · `GET/PATCH /auth/me` |
| 몸무게 | `GET/POST /weights` · `DELETE /weights/:id` (연결 글은 링크만 끊음) |
| 커뮤니티 | `GET /feed?scope=following|all&cursor=` · `POST /posts` · `GET /posts/:id` · `POST/DELETE /posts/:id/encourage` · `POST /posts/:id/comments` · `DELETE /posts/:id` · `GET /u/:handle` |
| 팔로우 (P2) | `POST/DELETE /u/:handle/follow` · `GET /u/:handle/{followers|following}` |
| 챌린지 (P2) | `GET/POST /challenges` · `GET /challenges/:id` · `POST /challenges/:id/join` · `DELETE .../leave` · `POST .../checkin` (`{date}`) · `DELETE .../checkin/:date` |
| 알림 (P2) | `GET /notifications?cursor=` · `GET /notifications/unread-count` · `POST /notifications/read` |
| 검색·차단 (P3a) | `GET /search?q=` → `{users,challenges,posts}` (LIKE, 각 12개) · `POST/DELETE /u/:handle/block` |
| 공개 (P3a) | `GET /c/:id` — **로그인 불필요**. 챌린지 공개 정보 + `member_count`·`active_this_week`·`sample_members` |
| 이미지 (P3b) | `POST /media` (multipart: file·kind∈{avatar,progress,post}) → Pillow 재인코딩·썸네일·`{id,url,thumb_url,w,h}` · `DELETE /media/:id` (미첨부만) · `GET /media/{key:path}` (파일 서빙, immutable 캐시) |
| 신고 (P3b) | `POST /reports` (`{target_kind∈{post,comment,user},target_id,reason}`, user 는 이름으로) · `GET /admin/reports?status=` (오너 전용) · `POST /admin/reports/:id/resolve` (`{action: delete_post|delete_comment|none}`) |
| 텔레그램 알림 (옵트인) | `POST /push/telegram/code` → `{code,deep_link}` (10분 · 일회용) · `GET/DELETE /push/telegram` · `POST /internal/telegram/{link,unlink}` (`X-Internal-Key`, 봇→API 로컬 호출) |
| 관리자 공지 | `GET/POST /admin/announcements` · `PATCH/DELETE /admin/announcements/:id` (오너 전용). `GET /notifications` 첫 페이지 응답에 `announcements`(활성 3개). `announcement`(title·body·link·starts_at·ends_at) 유효기간은 naive UTC, `_active_announcements()`. `parse_iso_utc()` 로 ISO(Z/offset/날짜만) → naive UTC |
| 등급 (자기돌봄 습관) | `app_user.rank_level`(1~5)·`rank_score` — `/auth/me`·`GET /u/:handle`·`FEED_SQL`(글 작성자)에 노출. `_refresh_rank()` 를 `POST /weights`·`.../checkin` 성공 시 호출, 점수가 이전보다 클 때만 갱신(하락 없음). 등급 상승 시 `notification`(kind='rank', rank_level) + 텔레그램 |

- bcrypt · PyJWT(HS256, 7일). 회원가입 폼은 비밀번호 확인 필드 포함(프론트 검증). `login_id`는 API 응답의 공개 컨텍스트(피드/프로필/댓글)에 절대 안 나감 — `name`만.
- **P3a 리치 프로필**: `PATCH /auth/me` 에 `link`(URL 정규화·검증) · `location` · `pinned_post_id`(0이하 = 해제, 본인 글만). `GET /u/:handle` 에 `link`·`location`·`post_count`·`challenge_count`·`pinned`(고정 글, `posts`에서 제외)·`trend_series`(public 한정, 스파크라인용).
- **P3a 차단**: `user_block`(blocker·blocked). 양방향 차단 시 피드·`/search`·`/u/:handle`(→`{blocked_by_me}` 또는 404)·알림에서 상호 숨김. `FEED_SQL` 에 `BLOCK_FILTER` 상시 적용(`{and_where}` 로 리팩터). 차단 시 서로 팔로우 해제. `delete_post` 는 이제 notification·pinned 참조도 정리.
- **P3b 이미지**: 파일 실체는 VM `MEDIA_DIR`, 메타는 `media` 테이블. `_process_image()` 가 Pillow 로 EXIF 제거·RGB 변환·리사이즈(표시 1280 / 아바타 400 정사각 / 썸네일 320) → JPEG 2장. 8MB·MIME(jpeg/png/webp)·유저당 200장 제한. `_own_media()` 로 첨부 시 소유·kind 검증. `_gc_media()` 가 글/기록 삭제 시 참조 없는 파일 정리. 아바타는 `PATCH /auth/me` `avatar_media_id`(0=제거), 글은 `POST /posts` `image_media_id`, 진행 사진은 `POST /weights` `photo_media_id`(**share=True 필수** — 비공개 사진 없음). `FEED_SQL`·`/u/:handle`·`GET /weights`·댓글·검색 응답에 이미지/아바타 URL 추가.
- **P3b 신고**: `report`(reporter·target_kind·target_id·reason·status). 중복(같은 reporter+target open)은 API 에서 무시. `OWNER_LOGIN_ID` env 로 오너 판별 → `/auth/me` 에 `is_owner`·`open_reports`. `_purge_post()` 로 관리자 글 삭제 재사용.
- **텔레그램 알림 (옵트인)**: 설정에서 `POST /push/telegram/code` → 딥링크(`t.me/<bot>?start=<코드>`). 봇이 `/start <코드>` 받으면 `update.effective_chat.id` + 코드로 `POST /internal/telegram/link` 호출 → `app_user.tg_chat_id` 저장. `notify()` 가 알림 행 넣은 뒤 `_maybe_push()` → 데몬 스레드로 `api.telegram.org/sendMessage`(fire-and-forget). 403/400 응답 시 `tg_chat_id` 자동 해제. `TELEGRAM_BOT_TOKEN` 없으면 전 기능 no-op(`/push/telegram` `available:false`). 코드 만료 비교는 `utcnow()`(naive UTC) — 세션 TZ 이슈 회피.
- **등급**: 흑연(1)·흑요석(2)·자수정(3)·사파이어(4)·다이아몬드(5) — `RANK_NAMES`. 점수 = 기록한 날수×1 + 역대 최장 연속 기록일(`_longest_streak()`, 현재 스트릭 아님)×2 + 완주 챌린지(체크인≥target_days)×30 + 챌린지 체크인 총수×1. `RANK_THRESHOLDS`/가중치는 `app.py` 상단 상수 — 초기값(0/50/200/600/1500)은 추정치, 실사용 데이터로 재조정 예정. **절대 하락하지 않음**(`_refresh_rank()` 이 새 점수 ≤ 저장값이면 무시) — 순위표 없음(오너만 보는 랭킹 페이지 없음), 개인 마일스톤. 기존 유저는 배포 시 1회 백필(`scratchpad/backfill_rank.py` 패턴, `_startup()` 수동 호출 후 전 유저 `_refresh_rank()`).
- `weight_privacy`(`private`/`trend`/`public`): 프로필의 몸무게 노출 + `log` 글의 weight 표시 여부(`public`만).
- 코드/시각: `parse_dt`는 사용자 벽시계 시각 그대로 저장(naive). `iso_z` 응답.
- 전역 `@app.exception_handler(Exception)` → `{"detail": ...}` JSON 500.

### DB (`healthweb` 스키마)

`sql/010_phase1_schema.sql` (**적용됨** — ADMIN으로 실행, `grant create sequence` 포함):
`app_user`(login_id PK · name unique · password_hash · bio · target_weight · weight_privacy) ·
`weight_entry`(login_id · logged_at · weight · note) ·
`post`(login_id · kind · body · weight_entry_id) · `encouragement`(PK post_id+login_id) · `post_comment`.
`verify_code` · 구 `app_user`(email/tg, username/user_name) drop됨.

`sql/020_phase2_schema.sql` (**적용됨**): `follow`(follower·followee) · `challenge`(owner·title·target_days) ·
`challenge_member` · `challenge_checkin`(check_date 'YYYY-MM-DD' 사용자 로컬) · `notification`(login_id 수신·kind·actor·post_id·read_at).
알림은 `notify()` 헬퍼가 encourage/comment/follow 시 생성(자기 행동 제외), 응원 취소 시 미읽음 알림 삭제.

`sql/030_phase3a_discovery.sql` (**적용됨** — healthweb 유저로 실행): `app_user` +`link`·`location`·`pinned_post_id` ·
`user_block`(blocker·blocked, **BLOCK 예약어라 user_block**) · 검색용 함수 인덱스(`lower(body)`·`lower(name)`·`lower(title)`).

`sql/040_phase3b_media.sql` (**적용됨** — healthweb 유저로 실행): `media`(login_id·kind·path·thumb_path·w·h·bytes) ·
`app_user` +`avatar_media_id` · `weight_entry` +`photo_media_id` · `post` +`image_media_id` ·
`report`(reporter·target_kind·target_id·reason·status). **MEDIA 도 예약어 아님(테이블명 그대로).**
주의: `scratchpad/apply_sql.py` 는 `;` 분리 시 문장 앞 `--` 주석이 붙은 청크를 통째로 건너뜀 → 파일 중간 주석 있으면 문장별로 실행할 것.

`sql/041_telegram_notify.sql` (**적용됨** — healthweb 유저): `app_user` +`tg_chat_id` · `tg_link_code`(code PK · login_id · created_at, TTL·1회용은 API 처리).

`sql/042_announcements.sql` (**적용됨** — healthweb 유저): `announcement`(title · body · link · starts_at · ends_at · created_by).

`sql/043_rank.sql` (**적용됨** — healthweb 유저): `app_user` +`rank_score`·`rank_level`(1~5, 기본 1) · `notification` +`rank_level` ·
`notification.kind` 체크 제약에 `'rank'` 추가(기존 제약은 이름 없이 생성돼 조회 후 drop 필요 — PL/SQL 블록으로 처리, `search_condition_vc` 는 **소문자 그대로 저장**되니 `upper()` 비교 필수).

`sql/011_migrate_owner_weights.sql` — 오너가 가입 후 `<LOGIN_ID>` 바꿔 실행 (구 텔레그램 이력 → weight_entry).

## VM 배포 (memo-agent)

- `/opt/health-web-api/` : `healthweb-api.service`(uvicorn :8000) + `caddy.service`(`healthweb21.duckdns.org`).
- `.env`: DB 자격증명 + `JWT_SECRET` + `ALLOW_ORIGIN=https://bemindfull21.github.io` + `MEDIA_DIR=/opt/health-web-api/media` · `MEDIA_BASE_URL=https://healthweb21.duckdns.org/media` · `OWNER_LOGIN_ID=bemindfull21` + **`INTERNAL_KEY`(봇과 공유, 텔레그램 링크 인증) · `TELEGRAM_BOT_TOKEN`(sendMessage) · `WEB_APP_URL=https://bemindfull21.github.io/healthweb` · `TELEGRAM_BOT_USERNAME=health_trainer21_bot`**.
- 이미지는 FastAPI 가 `GET /media/*` 로 직접 서빙 (Caddy 는 전체 프록시, 별도 설정 없음). `MEDIA_DIR` 은 `.gitignore` + systemd `User=opc` 쓰기 가능. **주기적으로 OCI 로 tar 백업 권장** (DB 백업엔 없음).
- `/internal/*` 는 Caddy 가 외부 404, 봇은 `127.0.0.1:8000` 직접 호출(우회) + `X-Internal-Key`.
- 재배포: `scp api/app.py api/requirements.txt opc@168.107.89.8:/opt/health-web-api/` → `ssh ... 'cd /opt/health-web-api && ./venv/bin/pip install -r requirements.txt && sudo systemctl restart healthweb-api'` (Pillow 추가됨).

## 폐기됨

- **텔레그램 봇 몸무게 입력** — `health-bot`의 `handle_message` 저장 로직 · `save_to_db` · `/link` · `/reset` 핸들러. 봇 완전 은퇴는 미결.
- **배치 ETL** — `refresh-data.yml` · `scripts/` · `data/users/*.json`. Phase 1은 API 직결만(정적 폴백 없음).
- 이메일 인증, 텔레그램 검증(`verify_code`), `dashboard.js`(→ `app.js`로 흡수).

## Phase 3a (2026-09-09) — 구현·배포됨

검색 · 리치 프로필(link·location·고정 글·스파크라인) · 차단 · 공개 페이지(`about.html` · `challenge.html?id=` · `/c/:id` API).
프론트: `SearchView`(상단바 🔍, debounce 350ms) · `Sparkline`(인라인 SVG) · `ProfileView` 확장(차단 메뉴·`blocked_by_me` 상태) ·
`PostView` 고정 토글 · `SettingsView` link·location. `404.html` 이 `/c/<id>`→`challenge.html`, `/about`→`about.html` 라우팅.
`challenge.html` 은 로그인 시 앱 `/challenges/:id` 로 리다이렉트, 아니면 `/c/:id` fetch 렌더.

## Phase 3b (2026-09-09) — 구현·배포됨

사진(**VM 파일시스템** — OCI 대신, 규모상) · 아바타 · 진행/글 사진(글 공유 시에만) · 신고 + 관리자 큐.
프론트: `Avatar`·`ImageUpload`(canvas 리사이즈)·`Lightbox` 컴포넌트 · `PostCard`/`PostView` 이미지·아바타 렌더 ·
`WeightModal`(진행 사진 항상 노출, 첨부 시 자동 공유)·`PostModal`·`SettingsView`(avatar-row) 이미지 첨부 · `PostView`·`ProfileView` ⋯메뉴에 신고 · `AdminReportsView`(`/admin`, `me.is_owner`면 설정에 링크) · `MeView` 표에 진행 사진 썸네일.
`MeView` 상단에 프로필 헤더(아바타·이름·"내 프로필 보기"·**설정** 버튼) — 이전엔 `/settings` 진입점이 자기 글의 이름 탭뿐이었음.

## 등급 (2026-09-11) — 구현·배포됨

흑연~다이아몬드 5단계, 광물 강도 은유. `about.html`에 도입 배경(등급=순위 아닌 굳기, 하락 없음) + 산정 기준표 + 등급 구간표 추가.
프론트: `RankBadge`(`RANK_NAME` 매핑) — `PostCard`·`PostView`(작성자 이름 옆) · `MeView`(`.me-head`) · `ProfileView`(`.phandle`)에 렌더.
`NotificationsView` 는 `kind==='rank'` 항목을 "🎉 {뱃지} 등급이 되었어요"로 특수 렌더, 클릭 시 `/me`.
CSS: `--rank-1~5` 토큰(라이트/다크) + `.rank-icon`(15px). `RankBadge`는 텍스트가 아니라 등급별 SVG 실루엣
(원→오각형→세로 결정→다이아 외곽선→컷팅면 있는 다이아몬드, `RANK_SHAPE`) — 이름은 `<title>`/`aria-label`로만.

## 미완 (Phase 3c+)

**3c 그룹** = `group_`·`group_member`(role) · `post.group_id` · `/feed?scope=group:` · 그룹 챌린지 · 알림 kind 확장 → `sql/050`.
상세·DB/API 델타는 커뮤니티 IA 아트팩트 §05. **착수 전 공유 비밀번호(`!Qazwsx123456`) 로테이션** (계속 미결).
공개 페이지 SEO 강화(Actions 프리렌더) · 사진 OCI 백업 크론.

## 프론트 P2 추가

탭바 5개(피드·챌린지·＋·알림·나, 알림 미읽음 뱃지). 피드 [팔로잉|전체] 세그(localStorage 저장).
`ChallengesView`/`ChallengeView`(데일리 체크인, 진행바)/`NotificationsView`(진입 시 read 처리).
`ChallengeModal`(＋ 시트에서). 프로필에 팔로우 버튼 + 팔로워/팔로잉 수.
