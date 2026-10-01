-- 054: 챌린지 비활성화 (오너가 저활용 챌린지를 닫음) ---------------------------
-- 비활성 = 읽기 전용: 목록·검색에서 숨김, 신규 참여·체크인·체크 해제 불가. 기존 기록·등급 점수는 보존.

alter table healthweb.challenge add (
  is_active      number(1) default 1 not null check (is_active in (0, 1)),
  deactivated_at timestamp
);

-- 비활성화 알림: 어떤 챌린지인지 가리킴
alter table healthweb.notification add (
  challenge_id number references healthweb.challenge(id)
);

-- kind 체크 제약에 'chal_end' 추가 (043 과 같은 패턴 — 기존 제약 조회 후 드롭)
begin
  for c in (
    select constraint_name from user_constraints
    where table_name = 'NOTIFICATION' and constraint_type = 'C'
      and upper(search_condition_vc) like '%KIND%IN%'
  ) loop
    execute immediate 'alter table healthweb.notification drop constraint ' || c.constraint_name;
  end loop;
end;
/

alter table healthweb.notification add constraint notification_kind_chk
  check (kind in ('encourage','comment','follow','rank','chal_end'));
