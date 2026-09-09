-- 오너의 텔레그램 몸무게 이력(admin.weight_log, tg_user_id='8974917114')을
-- 새 weight_entry 로 복사. healthweb 유저로 실행 (admin.weight_log 에 select 권한 있음).
-- ✅ 2026-09-09 실행됨: login_id='bemindfull21' (호랭이), 6행 이관.

insert into healthweb.weight_entry (login_id, logged_at, weight, note)
select 'bemindfull21', log_date, weight, quote
from admin.weight_log
where tg_user_id = '8974917114'
  and weight is not null;

commit;
