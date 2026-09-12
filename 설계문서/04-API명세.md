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
| GET | `/auth/me` | ✓ | — | 내 정보 + `rank_level/rank_name/rank_score` + (오너면) `is_owner, open_reports` |
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
| PATCH | `/posts/:id` | ✓ | `body, kind?` | 본인 글만(아니면 404), 본문 1~2000자. `kind` 생략 시 유지, 지정 시 유효성 검사. 이미지는 수정 불가 |
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
| POST | `/media` | multipart: `file, kind∈{avatar,progress,post,receipt}` | 8MB 제한, JPEG/PNG/WebP만, 유저당 200장. Pillow로 EXIF 제거·리사이즈(1280/400/320)·JPEG 2장(원본+썸네일) |
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

## ERP 구매 기록 (오너가 지정한 사용자 전용)

커뮤니티 핵심 기능과 무관한 오너용 개인 유틸리티. 아래 전부 `require_erp()`(`app_user.erp_access`) 게이트, 미부여 시 403.

| 메서드 | 경로 | 인증 | 바디 | 설명 |
|---|---|---|---|---|
| PATCH | `/admin/users/:handle/erp-access` | ✓(오너 전용) | `erp_access: bool` | `handle`은 `name`(닉네임). ERP 접근 권한 부여/회수 |
| POST | `/purchases/extract` | ✓(erp_access) | `media_id` | `kind='receipt'` 이미지를 Gemini 비전으로 분석 → `{items:[{shop_name,product_name,option_text,quantity,price_cny,price_krw,unit_price_krw,fx_rate,thumb_media_id,thumb_url}]}`. shop_name·product_name·option_text 는 한국어로 번역됨. Gemini 가 읽는 `price_cny` 는 화면에 보이는 **단가**(위안화)지만, 응답의 `price_cny`/`price_krw` 는 이미 `quantity`를 곱한 **총액**(위안화/원화)이다 — `unit_price_krw`(= `round(price_krw/quantity)`, 단가 원화)는 그 총액을 다시 수량으로 나눠 계산해 별도로 내려준다. 상품 사진 위치(`box_2d`)를 함께 받아 서버가 원본에서 크롭해 `item_thumb` media 로 저장(찾지 못하면 `thumb_media_id:null`). 상품 미검출 시 `items:[]`(정상). 최대 20개 항목까지만 처리. 10회/시간 제한 |
| POST | `/purchases` | ✓(erp_access) | `items[](thumb_media_id? 포함), order_date, source_media_id?` | 항목별 `product_name` 필수(빈 값은 건너뜀, 전부 빈 값이면 400). `order_date` 필수(빈 문자열이면 400 "구매일자를 입력해 주세요"). `thumb_media_id` 는 본인 소유·`kind='item_thumb'` 검증 후 연결. 서버가 항목마다 **구매ID**(`purchase_no`, `YYYYMMDD-NNN` — 같은 `login_id`+`order_date` 안에서 저장 순서대로 3자리 채번)와 `unit_price_krw`(`price_krw/quantity` 반올림)를 계산해 저장. `{ids:[...]}` 반환 |
| GET | `/purchases?cursor=&limit=&date_from=&date_to=&unreceived_only=` | ✓(erp_access) | — | 커서 페이지네이션(id desc). `unreceived_only=true` 면 기간 무시하고 `received=0`인 항목 전체. 아니면 `date_from`/`date_to`(YYYY-MM-DD, `coalesce(order_date, created_at 날짜)` 기준, 둘 다 생략 시 무제한)로 필터. 전체 합계 `total_krw`·`total_cny`는 현재 필터 범위 기준. 각 item 에 `purchase_no`·`unit_price_krw`·`thumb_url`·`received`(bool) |
| PATCH | `/purchases/:id` | ✓(erp_access) | `received: bool` | 입고 체크/해제. 본인 기록만(아니면 404) |
| DELETE | `/purchases/:id` | ✓(erp_access) | — | 본인 기록만(아니면 404). `sale_item`에 판매 이력이 있으면 400 "판매 이력이 있어 삭제할 수 없습니다"(먼저 그 판매들을 지워야 함). 삭제 성공 시 원본 영수증·상품 썸네일 미디어 GC |
| POST | `/expenses` | ✓(erp_access) | `expense_date, item_name, amount_krw, purchase_item_id?` | `expense_date`·`item_name`(공백 제거 후) 필수, 비면 400. `purchase_item_id`는 선택(옵션) — 값을 주면 본인 소유 구매건인지 검증(아니면 400 "구매ID를 확인해 주세요"), 생략하면 `null`로 저장되고 프론트는 이를 "기타"로 표시(2026-09-13: 처음엔 필수로 만들었다가, 특정 구매와 무관한 비용도 있어 선택으로 완화). `{id}` 반환 |
| GET | `/expenses?date_from=&date_to=` | ✓(erp_access) | — | `expense_date` 기준 기간 필터(둘 다 생략 시 전체). `expense_date desc, id desc` 정렬. `purchase_item` left join으로 `purchase_no` 포함(연결 안 된 옛 데이터는 null). `{items:[...], total_krw}` |
| PATCH | `/expenses/:id` | ✓(erp_access) | `amount_krw: float` | 금액 수정. 본인 기록만(아니면 404). `sale_item`(폐기 판매)이 이 비용을 참조 중이면 400 "폐기로 자동 생성된 비용은 금액을 변경할 수 없습니다" |
| DELETE | `/expenses/:id` | ✓(erp_access) | — | 본인 기록만(아니면 404). `sale_item`(폐기 판매)이 이 비용을 참조 중이면 400 "폐기 비용을 삭제하려면 판매 목록에서 폐기판매를 삭제하세요"(그 판매를 지우면 비용도 같이 지워짐) |
| GET | `/stock` | ✓(erp_access) | — | `received=1`이고 `quantity - sum(sale_qty) > 0`인 구매 건 목록(남은 재고는 저장 컬럼이 아니라 매번 `sale_item` 집계로 계산). 각 item: `purchase_item_id`·`purchase_no`·`product_name`·`remaining_qty`·`unit_price_krw`·`remaining_amount_krw`(=단가×남은수량)·`thumb_url` |
| POST | `/sales` | ✓(erp_access) | `items[](purchase_item_id, sale_qty, sale_price_krw), sale_date, is_waste?` | 항목마다 `purchase_item_id`가 본인 소유·`received=1`인지 확인 후, `sale_qty`가 그 시점 남은 재고를 넘으면 400. `is_waste=false`(기본)면 `sale_price_krw` 필수(0 이하 400), `sale_amount_krw = round(sale_price_krw*sale_qty)`. `is_waste=true`면 가격은 무시하고 `sale_price_krw`/`sale_amount_krw` 둘 다 0으로 저장하며, `수량×해당 구매건 unit_price_krw` 금액을 그 `sale_date`에 `expense_item`("상품 폐기", `purchase_item_id`=폐기 대상 그대로)으로 자동 생성해 `sale_item.expense_item_id`로 연결. `{ids:[...]}` 반환 |
| GET | `/sales?date_from=&date_to=` | ✓(erp_access) | — | `sale_date` 기준 기간 필터(생략 시 전체). `purchase_item` 조인으로 `purchase_no`·`product_name`·`thumb_url` 포함. 각 item에 `is_waste`(bool)·`waste_value_krw`(=`sale_qty`×해당 구매건 `unit_price_krw`, 화면 표시 전용 참고값 — `sale_amount_krw`는 폐기 건이면 계속 0이라 `total_krw`·손익 집계엔 영향 없음). `{items:[...], total_krw}` |
| PATCH | `/sales/:id` | ✓(erp_access) | `sale_qty: int, sale_price_krw: float` | 판매수량/가격 수정. `is_waste=true`인 건은 400(삭제 후 재등록 안내) — 폐기 건은 연결된 비용까지 있어 부분 수정을 허용하지 않음. 새 `sale_qty`는 "그 구매건 수량 − 이 판매를 뺀 다른 판매의 합"(capacity)을 넘으면 400. `sale_amount_krw` 재계산. 본인 기록만(아니면 404) |
| DELETE | `/sales/:id` | ✓(erp_access) | — | 본인 기록만(아니면 404). 삭제하면 재고가 그만큼 복원됨(남은 재고는 매번 계산이라 별도 처리 불필요). `is_waste=true`였다면 연결된 `expense_item`도 함께 삭제 |
| GET | `/profit?month_from=&month_to=` | ✓(erp_access) | — | 둘 다 `YYYY-MM` 필수(형식 오류·누락 400, `month_from>month_to` 400, 60개월 초과 400). 월별 `revenue`(=그 달 `sale_amount_krw` 합)·`cogs`(=그 달 판매수량×해당 구매건 `unit_price_krw` 합, 매출 인식 시점 기준 — 구매 시점이 아님)·`expense`(그 달 `expense_item` 합)·`profit`(`revenue-(cogs+expense)`)을 데이터 없는 달도 0으로 채워서 반환. `revenue`·`cogs` 모두 `is_waste=true` 판매는 제외(폐기 비용은 이미 `expense`에 별도로 잡혀 있어 중복 계산 방지). `{months:[...], total:{...}}` |

## 기타

| 메서드 | 경로 | 설명 |
|---|---|---|
| GET | `/healthz` | `{"ok": true}` — VM 헬스체크용 |
