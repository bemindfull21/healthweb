-- health-web(GitHub Pages 몸무게 조회 사이트)용 읽기 전용 DB 유저.
-- ADMIN으로 접속해 실행한다 (DBeaver: shindb_low, user ADMIN).
-- <PASSWORD> 를 실제 값으로 바꿔서 실행하고, 같은 값을 GitHub Secret `DB_PASSWORD` 에 넣는다.
-- (Autonomous DB 요건: 12자 이상, 대/소문자·숫자 각 1개 이상, " 와 공백 불가.)

create user healthweb identified by "<PASSWORD>";

grant connect to healthweb;
grant select on admin.weight_log to healthweb;   -- weight_log는 ADMIN 스키마 소유

-- 확인
-- select username, account_status from dba_users where username = 'HEALTHWEB';
