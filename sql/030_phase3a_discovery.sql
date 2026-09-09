-- Phase 3a: 발견 — 검색 · 리치 프로필 · 차단 · 공개 챌린지 페이지.
-- healthweb 유저로 1회 실행 (전부 자기 스키마). 추가만, 기존 테이블/데이터 안 건드림.
-- 주의: BLOCK 은 Oracle 예약어 → 테이블명 user_block (post_comment 와 같은 이유).

-- 리치 프로필: 한 줄 링크 · 지역 · 고정 글 ---------------------------------
alter table healthweb.app_user add (
  link            varchar2(200),
  location        varchar2(60),
  pinned_post_id  number references healthweb.post(id)
);

-- 차단: 서로의 글·프로필·검색·알림에서 숨김 -------------------------------
create table healthweb.user_block (
  blocker     varchar2(20) not null references healthweb.app_user(login_id),
  blocked     varchar2(20) not null references healthweb.app_user(login_id),
  created_at  timestamp default systimestamp not null,
  primary key (blocker, blocked)
);
create index user_block_blocked on healthweb.user_block(blocked);

-- 검색: 본문/이름/제목 LIKE 조회 성능용 (규모 작아 Oracle Text 불필요) ----
create index post_body_lower       on healthweb.post(lower(body));
create index app_user_name_lower   on healthweb.app_user(lower(name));
create index challenge_title_lower on healthweb.challenge(lower(title));
