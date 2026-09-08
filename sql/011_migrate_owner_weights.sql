-- 오너의 텔레그램 몸무게 이력(admin.weight_log, tg_user_id='8974917114')을
-- 새 weight_entry 로 복사. 오너가 새 username 으로 가입한 뒤 <USERNAME> 을 바꿔 실행.
-- healthweb 유저로 실행 (admin.weight_log 에 select 권한 있음).

insert into healthweb.weight_entry (username, logged_at, weight, note)
select '<USERNAME>', log_date, weight, quote
from admin.weight_log
where tg_user_id = '8974917114'
  and weight is not null;

commit;
