-- ERP 재고: 판매사이트 게시 여부
alter table healthweb.purchase_item add (
  is_listed number(1) default 0 not null
);
