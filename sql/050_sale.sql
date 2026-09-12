-- 050: ERP 재고/판매 — 구매 건에서 판매된 수량을 기록한다.
-- 남은 재고는 별도 컬럼으로 들고 있지 않고 purchase_item.quantity - sum(sale_item.sale_qty) 로 매번 계산한다
-- (동기화 버그를 피하기 위함).

create table healthweb.sale_item (
  id               number generated always as identity primary key,
  login_id         varchar2(20) not null references healthweb.app_user(login_id),
  purchase_item_id number not null references healthweb.purchase_item(id),
  sale_date        varchar2(10) not null,
  sale_qty         number(5) not null,
  sale_price_krw   number(14,2) not null,
  sale_amount_krw  number(14,2) not null,
  created_at       timestamp default systimestamp not null
);
create index sale_item_purchase on healthweb.sale_item(purchase_item_id);
create index sale_item_user on healthweb.sale_item(login_id, sale_date desc);
