-- 045: ERP(구매 기록) — 오너가 지정한 사용자만 접근 가능한 개인 도구.
-- Gemini로 주문 스크린샷에서 상품·가격을 추출해 저장한다. 위안화 원본 + 원화 환산 둘 다 보관.

alter table healthweb.app_user add (
  erp_access number(1) default 0 not null check (erp_access in (0,1))
);

create table healthweb.purchase_item (
  id            number generated always as identity primary key,
  login_id      varchar2(20) not null references healthweb.app_user(login_id),
  shop_name     varchar2(100),
  product_name  varchar2(300) not null,
  option_text   varchar2(200),
  quantity      number(5) default 1 not null,
  price_cny     number(12,2),
  price_krw     number(14,2),
  fx_rate       number(12,6),
  fx_at         timestamp,
  order_date    varchar2(10),
  source_media_id number references healthweb.media(id),
  created_at    timestamp default systimestamp not null
);
create index purchase_item_user on healthweb.purchase_item(login_id, id desc);

-- media.kind 체크 제약에 'receipt' 추가 (기존 제약은 이름 없이 생성돼 조회 후 drop 필요.
-- search_condition_vc 는 소문자 그대로 저장되니 upper() 비교 필수 — 043/044 에서 겪은 문제)
begin
  for c in (
    select constraint_name from user_constraints
    where table_name = 'MEDIA' and constraint_type = 'C'
      and upper(search_condition_vc) like '%KIND%IN%'
  ) loop
    execute immediate 'alter table healthweb.media drop constraint ' || c.constraint_name;
  end loop;
end;
/

alter table healthweb.media add constraint media_kind_chk
  check (kind in ('avatar','progress','post','receipt'));
