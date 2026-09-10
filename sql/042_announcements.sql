-- 관리자 공지 — 알림 페이지 상단 "공지" 구분자로 노출. healthweb 유저로 1회 실행.
-- 관리자 = OWNER_LOGIN_ID(bemindfull21). 유효기간(starts_at·ends_at)은 naive UTC 로 저장·비교.

create table healthweb.announcement (
  id          number generated always as identity primary key,
  title       varchar2(80),
  body        varchar2(1000) not null,
  link        varchar2(300),
  starts_at   timestamp,                 -- null = 즉시
  ends_at     timestamp,                 -- null = 무기한
  created_by  varchar2(20) not null references healthweb.app_user(login_id),
  created_at  timestamp default systimestamp not null
);
create index announcement_window on healthweb.announcement(starts_at, ends_at);
