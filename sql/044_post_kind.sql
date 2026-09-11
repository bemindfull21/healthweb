-- 044: 글 종류 재편 — log/routine/reflection/question 폐기 → 자랑/결심/반성/그냥
-- (brag/resolve/reflect/casual). 기존 데이터는 최선 추정으로 매핑하고,
-- 부정확하면 작성자가 새로 생긴 "수정" 기능으로 직접 고칠 수 있다.
--
-- 순서 중요: 기존 체크 제약을 먼저 지워야 UPDATE가 통과한다(새 값이 옛 제약을 위반하므로).

-- kind 체크 제약 제거 (기존 제약은 create table에 인라인으로 만들어져 이름이 없음 —
-- 조회 후 drop 필요. search_condition_vc는 소문자 그대로 저장되니 upper() 비교 필수)
begin
  for c in (
    select constraint_name from user_constraints
    where table_name = 'POST' and constraint_type = 'C'
      and upper(search_condition_vc) like '%KIND%IN%'
  ) loop
    execute immediate 'alter table healthweb.post drop constraint ' || c.constraint_name;
  end loop;
end;
/

update healthweb.post set kind = 'casual'  where kind = 'log';       -- 자동 몸무게 기록 글
update healthweb.post set kind = 'resolve' where kind = 'routine';   -- 루틴 실천 ≈ 결심
update healthweb.post set kind = 'reflect' where kind = 'reflection';
update healthweb.post set kind = 'casual'  where kind = 'question';  -- 질문은 넷 중 그냥에 가장 가까움

alter table healthweb.post add constraint post_kind_chk
  check (kind in ('brag','resolve','reflect','casual'));
