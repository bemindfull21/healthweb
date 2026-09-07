-- 웹 계정 테이블. ADMIN으로 1회 실행. (2026-09-08 적용됨)
grant create table to healthweb;
alter user healthweb quota 50m on data;

create table healthweb.app_user (
  id             number generated always as identity primary key,
  email          varchar2(320) not null unique,
  password_hash  varchar2(100) not null,          -- bcrypt 60자
  tg_user_id     varchar2(20)  not null unique,
  verified       char(1) default 'N' not null,     -- 텔레그램 /link 인증 여부
  target_weight  number(5,2),                      -- 목표 몸무게(kg), nullable
  created_at     timestamp default systimestamp not null,
  last_login_at  timestamp
);
