-- Ashdod rent bot schema. Run once in Supabase: SQL Editor -> New query -> paste -> Run.

create table if not exists users (
  chat_id     bigint primary key,
  first_name  text,
  username    text,
  approved    boolean not null default false,
  is_admin    boolean not null default false,
  paused      boolean not null default false,
  state       text,             -- what free-text reply the bot is waiting for
  state_data  jsonb,
  created_at  timestamptz not null default now()
);

create table if not exists searches (
  id                bigserial primary key,
  chat_id           bigint not null references users on delete cascade,
  name              text not null default 'החיפוש שלי',
  active            boolean not null default false,
  neighborhoods     text[] not null default '{}',   -- empty = all of Ashdod
  rooms_min         numeric,
  rooms_max         numeric,
  price_min         int,
  price_max         int,
  need_mamad        boolean not null default false,
  need_balcony      boolean not null default false,
  need_parking      boolean not null default false,
  need_elevator     boolean not null default false,
  no_broker         boolean not null default false,
  exclude_keywords  text[] not null default '{}',
  include_keywords  text[] not null default '{}',
  created_at        timestamptz not null default now()
);
create index if not exists searches_chat on searches (chat_id);

create table if not exists listings (
  id            bigserial primary key,
  source        text not null,
  source_id     text not null,
  group_id      bigint,          -- same apartment across sources share a group (id of first listing)
  url           text not null,
  title         text,
  neighborhood  text,
  street        text,
  house_number  text,
  rooms         numeric,
  floor         int,
  sqm           numeric,
  price         int,
  has_mamad     boolean,
  has_balcony   boolean,
  has_parking   boolean,
  has_elevator  boolean,
  is_broker     boolean,
  phone         text,
  description   text,
  images        text[] not null default '{}',
  entry_date    text,
  published_at  timestamptz,     -- when the ad was first posted (if the site says)
  bumped_at     timestamptz,     -- last bump / update shown by the site
  first_seen    timestamptz not null default now(),
  unique (source, source_id)
);
create index if not exists listings_first_seen on listings (first_seen desc);
create index if not exists listings_group on listings (group_id);

create table if not exists alerts (
  id           bigserial primary key,
  chat_id      bigint not null references users on delete cascade,
  group_id     bigint not null,
  listing_id   bigint not null references listings on delete cascade,
  search_id    bigint references searches on delete set null,
  message_id   bigint,
  status       text not null default 'sent',   -- sent | saved | dismissed
  created_at   timestamptz not null default now(),
  unique (chat_id, group_id)
);

create table if not exists kv (
  key    text primary key,
  value  jsonb
);

-- Only the service-role key (used by the scraper and the bot) may touch these tables.
alter table users    enable row level security;
alter table searches enable row level security;
alter table listings enable row level security;
alter table alerts   enable row level security;
alter table kv       enable row level security;
