-- Publish / bump dates for listings. Run once in Supabase SQL Editor on databases created before this change.
alter table listings add column if not exists published_at timestamptz;
alter table listings add column if not exists bumped_at timestamptz;
