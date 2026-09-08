-- Phase 1 스키마. ADMIN으로 1회 실행. 재실행 시 기존 테이블 삭제됨(실사용 데이터 없을 때만).
--
--  login_id : 로그인 아이디. 영문 소문자+숫자. 비공개. 로그인·비밀번호 재설정에만 사용.
--  name     : 표시 이름. 공개 handle (피드·프로필·URL). 둘 다 unique.

grant create sequence to healthweb;

drop table healthweb.post_comment   cascade constraints;
drop table healthweb.encouragement  cascade constraints;
drop table healthweb.post           cascade constraints;
drop table healthweb.weight_entry   cascade constraints;
drop table healthweb.app_user       cascade constraints;

-- 계정 -----------------------------------------------------------------
create table healthweb.app_user (
  login_id        varchar2(20)  primary key,             -- 비공개. ^[a-z0-9]{3,20}$
  name            varchar2(40)  not null unique,          -- 공개 handle
  password_hash   varchar2(100) not null,
  bio             varchar2(200),
  target_weight   number(5,2),
  weight_privacy  varchar2(10) default 'private' not null
                  check (weight_privacy in ('private','trend','public')),
  created_at      timestamp default systimestamp not null,
  last_login_at   timestamp
);

-- 몸무게 기록 --------------------------------------------------------------
create table healthweb.weight_entry (
  id          number generated always as identity primary key,
  login_id    varchar2(20)  not null references healthweb.app_user(login_id),
  logged_at   timestamp     not null,
  weight      number(5,2)   not null,
  note        varchar2(500),
  created_at  timestamp default systimestamp not null
);
create index weight_entry_user on healthweb.weight_entry(login_id, logged_at);

-- 커뮤니티 -------------------------------------------------------------
create table healthweb.post (
  id               number generated always as identity primary key,
  login_id         varchar2(20) not null references healthweb.app_user(login_id),
  kind             varchar2(12) not null
                   check (kind in ('log','routine','reflection','question')),
  body             varchar2(2000) not null,
  weight_entry_id  number references healthweb.weight_entry(id),
  created_at       timestamp default systimestamp not null
);
create index post_created on healthweb.post(created_at desc);

create table healthweb.encouragement (
  post_id     number not null references healthweb.post(id),
  login_id    varchar2(20) not null references healthweb.app_user(login_id),
  created_at  timestamp default systimestamp not null,
  primary key (post_id, login_id)
);

create table healthweb.post_comment (
  id          number generated always as identity primary key,
  post_id     number not null references healthweb.post(id),
  login_id    varchar2(20) not null references healthweb.app_user(login_id),
  body        varchar2(1000) not null,
  created_at  timestamp default systimestamp not null
);
create index post_comment_post on healthweb.post_comment(post_id, created_at);
