-- 048: 구매ID(구매일자-일련번호 3자리, 예 20260910-001) + 단가(원화) 컬럼 추가.
-- 기존 price_cny/price_krw는 "단가 × 환율"만 넣고 있어 수량이 반영 안 된 값이었다(실질적 버그).
-- 이번에 API 쪽에서 수량을 곱한 "금액(총액)"으로 의미를 바로잡고, 단가(원화)=금액(원화)/수량 을 새 컬럼에 둔다.

alter table healthweb.purchase_item add (
  purchase_no    varchar2(12),
  unit_price_krw number(14,2)
);

-- 기존 행 백필: login_id+order_date 그룹 안에서 id 오름차순으로 일련번호 3자리 부여
merge into healthweb.purchase_item t
using (
  select id,
         replace(order_date, '-', '') || '-' ||
         to_char(row_number() over (partition by login_id, order_date order by id), 'FM000') as no
  from healthweb.purchase_item
  where order_date is not null
) s
on (t.id = s.id)
when matched then update set t.purchase_no = s.no;

alter table healthweb.purchase_item modify (purchase_no not null);
create unique index purchase_item_no on healthweb.purchase_item(login_id, purchase_no);
