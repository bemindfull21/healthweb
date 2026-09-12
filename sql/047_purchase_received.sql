alter table healthweb.purchase_item add (
  received number(1) default 0 not null check (received in (0,1))
);

create index purchase_item_received on healthweb.purchase_item(login_id, received);
