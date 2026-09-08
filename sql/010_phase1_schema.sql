-- Phase 1: 커뮤니티 전환. ADMIN으로 1회 실행.
-- app_user 재생성 (기존 계정 1개 = 오너 테스트 계정, 삭제됨. 새 username 플로우로 재가입).
-- 오너 몸무게 이력은 011_migrate_owner_weights.sql 로 옮긴다.

grant create sequence to healthweb;   -- identity 컬럼용 (없으면 ORA-01031)

drop table healthweb.verify_code cascade constraints;
drop table healthweb.app_user cascade constraints;

-- 계정 -----------------------------------------------------------------
create table healthweb.app_user (
  username        varchar2(20)  primary key,             -- 소문자, ^[a-z0-9]{3,20}$, 공개 handle
  user_name       varchar2(40)  not null,                -- 비공개. 비밀번호 재설정 확인용 (노출 안 함)
  password_hash   varchar2(100) not null,                -- bcrypt
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
  username    varchar2(20)  not null references healthweb.app_user(username),
  logged_at   timestamp     not null,                    -- 측정 시각 (사용자 입력)
  weight      number(5,2)   not null,
  note        varchar2(500),
  created_at  timestamp default systimestamp not null
);
create index weight_entry_user on healthweb.weight_entry(username, logged_at);

-- 커뮤니티 -------------------------------------------------------------
create table healthweb.post (
  id               number generated always as identity primary key,
  username         varchar2(20) not null references healthweb.app_user(username),
  kind             varchar2(12) not null
                   check (kind in ('log','routine','reflection','question')),
  body             varchar2(2000) not null,
  weight_entry_id  number references healthweb.weight_entry(id),
  created_at       timestamp default systimestamp not null
);
create index post_created on healthweb.post(created_at desc);

create table healthweb.encouragement (
  post_id     number not null references healthweb.post(id),
  username    varchar2(20) not null references healthweb.app_user(username),
  created_at  timestamp default systimestamp not null,
  primary key (post_id, username)
);

-- COMMENT 는 Oracle 예약어 → post_comment
create table healthweb.post_comment (
  id          number generated always as identity primary key,
  post_id     number not null references healthweb.post(id),
  username    varchar2(20) not null references healthweb.app_user(username),
  body        varchar2(1000) not null,
  created_at  timestamp default systimestamp not null
);
create index post_comment_post on healthweb.post_comment(post_id, created_at);
