-- 052: 비용 건에 관련 구매ID(purchase_item_id)를 연결 — 신규 등록 시 API에서 필수로 검증한다.
-- 기존 행(수동 등록·폐기 자동생성)은 이 컬럼이 비어 있을 수 있어 컬럼 자체는 nullable 로 둔다.

alter table healthweb.expense_item add (
  purchase_item_id number references healthweb.purchase_item(id)
);
create index expense_item_purchase on healthweb.expense_item(purchase_item_id);
