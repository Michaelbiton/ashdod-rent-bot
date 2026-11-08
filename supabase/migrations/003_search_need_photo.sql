-- "Photo required" option for searches. Run once on databases created before this change.
alter table searches add column if not exists need_photo boolean not null default false;
