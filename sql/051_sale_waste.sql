-- 051: ERP 판매 삭제 + 재고 폐기 기능.
-- is_waste: 재고를 판매가 아니라 폐기로 처리한 건(매출·구매원가 계산에서 제외 — 대신 expense_item에 비용으로 기록).
-- expense_item_id: 폐기 건이 자동 생성한 expense_item 을 가리킴 — 이 판매 건을 지우면 그 비용도 같이 지운다.

alter table healthweb.sale_item add (
  is_waste         number(1) default 0 not null check (is_waste in (0,1)),
  expense_item_id  number references healthweb.expense_item(id)
);
