-- Phase 3b: 사진 — 아바타 · 진행 사진 · 글 이미지 + 신고.
-- healthweb 유저로 1회 실행 (전부 자기 스키마). 추가만.
-- 파일 실체는 VM 파일시스템(MEDIA_DIR), 이 테이블은 메타·소유·쿼터·모더레이션 추적용.

create table healthweb.media (
  id          number generated always as identity primary key,
  login_id    varchar2(20) not null references healthweb.app_user(login_id),
  kind        varchar2(12) not null check (kind in ('avatar','progress','post')),
  path        varchar2(160) not null,          -- MEDIA_DIR 기준 상대 키 (예: 'a1/b2c3...jpg')
  thumb_path  varchar2(160),
  width       number(6),
  height      number(6),
  bytes       number(12),
  created_at  timestamp default systimestamp not null
);
create index media_owner on healthweb.media(login_id, id desc);

alter table healthweb.app_user     add (avatar_media_id number references healthweb.media(id));
alter table healthweb.weight_entry add (photo_media_id  number references healthweb.media(id));
alter table healthweb.post         add (image_media_id  number references healthweb.media(id));

-- 신고 큐 ------------------------------------------------------------------
create table healthweb.report (
  id           number generated always as identity primary key,
  reporter     varchar2(20) not null references healthweb.app_user(login_id),
  target_kind  varchar2(10) not null check (target_kind in ('post','comment','user')),
  target_id    varchar2(40) not null,          -- post id / comment id / login_id
  reason       varchar2(300),
  status       varchar2(10) default 'open' not null check (status in ('open','closed')),
  created_at   timestamp default systimestamp not null
);
create index report_open on healthweb.report(status, id desc);
-- 중복 신고(같은 reporter+target 의 open 건)는 API 에서 SELECT 후 무시.
