-- 텔레그램 알림(옵트인) — 3b 후속. healthweb 유저로 1회 실행.
-- 연결은 일회용 코드 + 딥링크. chat_id 는 봇이 메시지에서 자동으로 얻는다.

alter table healthweb.app_user add (tg_chat_id number);

create table healthweb.tg_link_code (
  code        varchar2(24) primary key,
  login_id    varchar2(20) not null references healthweb.app_user(login_id),
  created_at  timestamp default systimestamp not null
);
-- TTL(10분)·단건 사용은 API 에서 처리(만료 코드는 재발급 시 정리).
