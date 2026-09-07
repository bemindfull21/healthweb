-- link 인증 / 비밀번호 재설정 코드. ADMIN으로 1회 실행. (2026-09-08 적용됨)
-- 코드 만료(10분)는 API 로직에서 created_at 으로 체크.
create table healthweb.verify_code (
  code        varchar2(8)   primary key,
  purpose     varchar2(10)  not null check (purpose in ('link','reset')),
  email       varchar2(320) not null,
  tg_user_id  varchar2(20)  not null,           -- 계정에 등록된 값(대조용)
  new_hash    varchar2(100),                    -- reset일 때 새 비번 해시, link이면 NULL
  consumed    char(1) default 'N' not null check (consumed in ('Y','N')),
  created_at  timestamp default systimestamp not null
);

create index verify_code_email on healthweb.verify_code(email);
