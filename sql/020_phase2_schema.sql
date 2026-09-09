-- Phase 2: 팔로우 · 챌린지 · 알림. ADMIN(또는 healthweb)으로 1회 실행. 추가만, 기존 테이블 안 건드림.

-- 팔로우 ---------------------------------------------------------------
create table healthweb.follow (
  follower    varchar2(20) not null references healthweb.app_user(login_id),
  followee    varchar2(20) not null references healthweb.app_user(login_id),
  created_at  timestamp default systimestamp not null,
  primary key (follower, followee)
);
create index follow_followee on healthweb.follow(followee);

-- 챌린지 (데일리 체크인) ------------------------------------------------
create table healthweb.challenge (
  id           number generated always as identity primary key,
  owner        varchar2(20)  not null references healthweb.app_user(login_id),
  title        varchar2(60)  not null,
  description  varchar2(500),
  target_days  number(3)     not null check (target_days between 1 and 365),
  created_at   timestamp default systimestamp not null
);
create index challenge_created on healthweb.challenge(created_at desc);

create table healthweb.challenge_member (
  challenge_id number       not null references healthweb.challenge(id),
  login_id     varchar2(20) not null references healthweb.app_user(login_id),
  joined_at    timestamp default systimestamp not null,
  primary key (challenge_id, login_id)
);
create index challenge_member_user on healthweb.challenge_member(login_id);

create table healthweb.challenge_checkin (
  challenge_id number       not null references healthweb.challenge(id),
  login_id     varchar2(20) not null references healthweb.app_user(login_id),
  check_date   varchar2(10) not null,   -- 'YYYY-MM-DD' (사용자 로컬 기준일)
  created_at   timestamp default systimestamp not null,
  primary key (challenge_id, login_id, check_date)
);

-- 알림 ---------------------------------------------------------------
create table healthweb.notification (
  id         number generated always as identity primary key,
  login_id   varchar2(20) not null references healthweb.app_user(login_id),  -- 받는 사람
  kind       varchar2(12) not null check (kind in ('encourage','comment','follow')),
  actor      varchar2(20) not null references healthweb.app_user(login_id),  -- 행동한 사람
  post_id    number references healthweb.post(id),
  read_at    timestamp,
  created_at timestamp default systimestamp not null
);
create index notification_user on healthweb.notification(login_id, id desc);
