-- ai_public_projects table
-- Run this in the Supabase SQL Editor (Dashboard → SQL Editor → New query)

create table if not exists public.ai_public_projects (
  id               bigserial primary key,
  github_id        bigint unique not null,          -- dedup key
  project          text not null,                   -- repo full_name e.g. "org/repo"
  category         text not null default 'AI',      -- derived from topics
  type             text not null default 'Library',  -- derived from topics/description
  description      text,
  creator          text not null,                   -- repo owner login
  date             date not null,                   -- last pushed date (truncated to day)
  source           text not null,                   -- canonical GitHub URL
  stars            integer not null default 0,
  starred          boolean not null default false,  -- manual curation flag (set in UI)
  topics           text[],                          -- raw GitHub topics array
  language         text,                            -- primary language
  synced_at        timestamptz not null default now()
);

-- Fast lookups by category and star count (used by the site table)
create index if not exists idx_ai_public_projects_category on public.ai_public_projects (category);
create index if not exists idx_ai_public_projects_stars    on public.ai_public_projects (stars desc);
create index if not exists idx_ai_public_projects_date     on public.ai_public_projects (date desc);

-- RLS: public read, service-role write only
alter table public.ai_public_projects enable row level security;

-- Drop before re-creating to make this script idempotent
drop policy if exists "Public read access"    on public.ai_public_projects;
drop policy if exists "Service role write"    on public.ai_public_projects;

create policy "Public read access"
  on public.ai_public_projects
  for select
  using (true);

-- The sync script uses the service-role key, which bypasses RLS entirely.
-- This policy guards any future non-service writes (e.g. Edge Functions with anon key).
create policy "Service role write"
  on public.ai_public_projects
  for all
  using     (auth.role() = 'service_role')
  with check (auth.role() = 'service_role');
