-- 049: ERP 비용 기능 — 비용발생일자/비용항목/비용(원화) 기록.

create table healthweb.expense_item (
  id           number generated always as identity primary key,
  login_id     varchar2(20) not null references healthweb.app_user(login_id),
  expense_date varchar2(10) not null,
  item_name    varchar2(200) not null,
  amount_krw   number(14,2) not null,
  created_at   timestamp default systimestamp not null
);
create index expense_item_user on healthweb.expense_item(login_id, expense_date desc);
