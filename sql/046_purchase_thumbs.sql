alter table healthweb.purchase_item add (
  thumb_media_id number references healthweb.media(id)
);

-- media.kind 체크 제약에 'purchase_thumb' 추가 (drop old unnamed constraint via upper() search, then add new)
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
  check (kind in ('avatar','progress','post','receipt','item_thumb'));
