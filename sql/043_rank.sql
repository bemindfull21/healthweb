-- 043: 등급(자기돌봄 습관이 단단해진 정도) ------------------------------
-- 흑연 < 흑요석 < 자수정 < 사파이어 < 다이아몬드. 누적 점수, 하락 없음.

alter table healthweb.app_user add (
  rank_score number default 0 not null,
  rank_level number(1) default 1 not null
);

alter table healthweb.notification add (
  rank_level number(1)
);

-- kind 체크 제약에 'rank' 추가 (기존 제약은 이름 없이 생성돼 시스템이 이름을 붙였으므로 조회해서 드롭)
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
  check (kind in ('encourage','comment','follow','rank'));
