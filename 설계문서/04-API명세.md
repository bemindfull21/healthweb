# API 명세

- Base URL: `https://healthweb21.duckdns.org` (VM, Caddy → uvicorn :8000)
- 인증: `Authorization: Bearer <JWT>` (HS256, 7일 만료, `sub`=login_id). 미인증 401.
- 공통 에러 포맷: `{"detail": "메시지"}` (전역 `exception_handler`)
- `login_id`는 어떤 응답에도 타인에게 노출되지 않는다. 공개 식별자는 항상 `name`.

## 인증

| 메서드 | 경로 | 인증 | 바디 | 설명 |
|---|---|---|---|---|
| GET | `/auth/check?login_id=&name=` | ✗ | — | 아이디/이름 중복 확인, 둘 다 선택적 |
| POST | `/auth/signup` | ✗ | `login_id, name, password, target_weight?` | 가입, `{token}` 반환 |
| POST | `/auth/signin` | ✗ | `login_id, password` | 로그인, `{token}` |
| POST | `/auth/reset` | ✗ | `login_id, name, new_password` | 이름 일치 확인 후 재설정 |
| GET | `/auth/me` | ✓ | — | 내 정보 + `rank_level/rank_name` + (오너면) `is_owner, open_reports` |
| PATCH | `/auth/me` | ✓ | `MePatch` (전부 optional) | `avatar_media_id`/`pinned_post_id` ≤0 = 제거, 비밀번호 변경 시 `current_password` 필요 |

## 몸무게

| 메서드 | 경로 | 인증 | 바디 | 설명 |
|---|---|---|---|---|
| GET | `/weights` | ✓ | — | 내 기록 목록(`entries`) |
| POST | `/weights` | ✓ | `weight, logged_at?, note?, share=false, photo_media_id?` | `share=True`면 `post` 자동 생성. 사진은 `share=True`일 때만 허용. 성공 시 `_refresh_rank()` 호출 |
| DELETE | `/weights/:id` | ✓ | — | 기록 삭제, 연결된 글은 `weight_entry_id`만 끊음(글은 안 지움) |

## 피드 · 글

| 메서드 | 경로 | 인증 | 바디 | 설명 |
|---|---|---|---|---|
| GET | `/feed?scope=following\|all&cursor=&limit=` | ✓ | — | 커서 페이지네이션(id 기준), 차단 상호 필터 적용 |
| POST | `/posts` | ✓ | `kind, body, weight_entry_id?, image_media_id?` | |
| GET | `/posts/:id` | ✓ | — | 글 상세 + `comments[]`(작성자 아바타 포함) |
| PATCH | `/posts/:id` | ✓ | `body` | 본인 글만(아니면 404), 본문 1~2000자. `kind`·이미지는 수정 불가 |
| POST/DELETE | `/posts/:id/encourage` | ✓ | — | 응원 토글, 취소 시 미읽음 알림도 삭제 |
| POST | `/posts/:id/comments` | ✓ | `body` | |
| DELETE | `/posts/:id` | ✓ | — | 본인 글만, `_purge_post()`(댓글·응원·알림·고정참조·미디어 GC까지 정리) |
| GET | `/u/:handle` | ✓ | — | 공개 프로필. 차단 상태면 `{blocked_by_me}` 또는 404 |

## 팔로우

| 메서드 | 경로 |
|---|---|
| POST/DELETE | `/u/:handle/follow` |
| GET | `/u/:handle/followers` · `/u/:handle/following` |

## 챌린지

| 메서드 | 경로 | 바디 | 설명 |
|---|---|---|---|
| GET | `/challenges` | — | 목록(50개), 참여 중이면 `progress` 포함 |
| POST | `/challenges` | `title, description?, target_days` | 생성 시 owner가 자동 참여. 5회/시간 제한 |
| GET | `/challenges/:id` | — | 상세 + `my_progress/my_streak/my_dates` + 멤버별 진행률 |
| POST | `/challenges/:id/join` / DELETE `/leave` | — | |
| POST | `/challenges/:id/checkin` | `date` | 중복 무시(`IntegrityError` catch). 성공 시 `_refresh_rank()` |
| DELETE | `/challenges/:id/checkin/:date` | — | |

## 알림

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/notifications?cursor=&limit=` | 첫 페이지에만 `announcements`(활성 공지 3개) 포함 |
| GET | `/notifications/unread-count` | |
| POST | `/notifications/read` | 내 미읽음 전체 읽음 처리 |

`notification.kind` ∈ `encourage · comment · follow · rank`. `rank`는 `actor=본인`(자기 알림 예외 처리), `rank_level` 컬럼에 등급 저장.

## 검색 · 차단

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/search?q=` | `{users, challenges, posts}` 각 12개, LIKE 검색 |
| POST/DELETE | `/u/:handle/block` | 양방향 숨김, 차단 시 서로 언팔로우 |

## 공개(비로그인)

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/c/:id` | 챌린지 공개 정보 + `member_count · active_this_week · sample_members` |

## 이미지

| 메서드 | 경로 | 바디/파라미터 | 설명 |
|---|---|---|---|
| POST | `/media` | multipart: `file, kind∈{avatar,progress,post}` | 8MB 제한, JPEG/PNG/WebP만, 유저당 200장. Pillow로 EXIF 제거·리사이즈(1280/400/320)·JPEG 2장(원본+썸네일) |
| DELETE | `/media/:id` | — | 아무 데도 참조 안 될 때만 삭제 |
| GET | `/media/{key:path}` | — | 파일 서빙, `Cache-Control: immutable`, 경로 이탈 방지 |

## 신고 · 모더레이션 (오너 전용 구간 포함)

| 메서드 | 경로 | 바디 | 설명 |
|---|---|---|---|
| POST | `/reports` | `target_kind∈{post,comment,user}, target_id, reason?` | user는 이름으로 받아 login_id 변환. 중복(같은 신고자+대상 open) 무시. 10회/시간 제한 |
| GET | `/admin/reports?status=open\|closed` | — | **오너 전용**. 대상 미리보기 포함(삭제됐으면 `{gone:true}`) |
| POST | `/admin/reports/:id/resolve` | `action: null\|'delete_post'\|'delete_comment'` | 같은 대상의 열린 신고 전부 함께 닫힘. **신고자에게 알림 없음** |

## 텔레그램 알림 연동 (옵트인)

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/push/telegram/code` | `{code, deep_link}` 발급, 10분 TTL·1회용, 5회/시간 제한 |
| GET | `/push/telegram` | `{linked, available}` (`TELEGRAM_BOT_TOKEN` 없으면 `available:false`) |
| DELETE | `/push/telegram` | 연동 해제 |
| POST | `/internal/telegram/link` / `/internal/telegram/unlink` | `X-Internal-Key` 필요, **외부 노출 안 됨**(Caddy가 `/internal/*` 404 처리, 봇이 `127.0.0.1:8000` 직접 호출) |

## 관리자 공지 (오너 전용)

| 메서드 | 경로 | 바디 | 설명 |
|---|---|---|---|
| GET/POST | `/admin/announcements` | `title?, body, link?, starts_at?, ends_at?` | |
| PATCH/DELETE | `/admin/announcements/:id` | | |

## 기타

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/healthz` | `{"ok": true}` — VM 헬스체크용 |
