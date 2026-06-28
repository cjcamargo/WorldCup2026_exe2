create table if not exists users (
  participant text primary key,
  pin_hash text not null,
  role text not null default 'player',
  active boolean not null default true
);

create table if not exists polla_groups (
  group_id uuid primary key default gen_random_uuid(),
  name text not null,
  invite_code text not null unique,
  created_by text not null references users(participant),
  active boolean not null default true,
  created_at timestamptz not null default now(),
  competition_mode text not null default 'full' check (competition_mode in ('group_stage', 'knockout', 'full'))
);

create table if not exists group_memberships (
  group_id uuid not null references polla_groups(group_id) on delete cascade,
  participant text not null references users(participant) on delete cascade,
  role text not null default 'player',
  status text not null default 'pending',
  joined_at timestamptz not null default now(),
  primary key (group_id, participant),
  constraint group_memberships_role_check check (role in ('admin', 'player')),
  constraint group_memberships_status_check check (status in ('pending', 'active', 'rejected'))
);

create table if not exists matches (
  match_id text primary key,
  phase text,
  team_a text not null,
  team_b text not null,
  kickoff_at timestamptz,
  status text not null default 'scheduled'
);

create table if not exists predictions (
  group_id uuid not null references polla_groups(group_id) on delete cascade,
  participant text not null references users(participant),
  match_id text not null references matches(match_id),
  team_a text not null,
  team_b text not null,
  goals_a_pred int,
  goals_b_pred int,
  qualified_team_pred text,
  updated_at timestamptz,
  primary key (group_id, participant, match_id)
);

create table if not exists group_picks (
  group_id uuid not null references polla_groups(group_id) on delete cascade,
  participant text not null references users(participant),
  "group" text not null,
  first text,
  second text,
  third text,
  updated_at timestamptz,
  primary key (group_id, participant, "group")
);

create table if not exists final_picks (
  group_id uuid not null references polla_groups(group_id) on delete cascade,
  participant text not null references users(participant),
  champion text,
  runner_up text,
  third_place text,
  updated_at timestamptz,
  primary key (group_id, participant)
);

create table if not exists results (
  match_id text primary key,
  team_a text not null,
  team_b text not null,
  goals_a_real int,
  goals_b_real int,
  status text not null default 'scheduled',
  phase text,
  kickoff_at timestamptz,
  source text,
  source_url text,
  confirmed boolean not null default false
  ,final_goals_a int
  ,final_goals_b int
  ,penalties_a int
  ,penalties_b int
  ,qualified_team text
  ,decision text
);

create table if not exists audit_log (
  id bigserial primary key,
  detected_at timestamptz not null,
  participant text not null,
  match_id text not null,
  field text not null,
  old_value text,
  new_value text,
  status text not null,
  reason text
  ,group_id uuid references polla_groups(group_id) on delete set null
);

create table if not exists settings (
  key text primary key,
  value text
);

create table if not exists ranking (
  group_id uuid references polla_groups(group_id),
  participant text primary key,
  points int not null default 0,
  rank int
);

create table if not exists detail (
  id bigserial primary key,
  group_id uuid references polla_groups(group_id),
  participant text,
  match_id text,
  team_a text,
  team_b text,
  pred_score text,
  real_score text,
  points int
);

alter table ranking add column if not exists group_id uuid references polla_groups(group_id);
alter table detail add column if not exists group_id uuid references polla_groups(group_id);

insert into polla_groups (name, invite_code, created_by, competition_mode)
select 'Exe2', 'EXE2', participant, 'group_stage'
from users
where participant = 'admin'
on conflict (invite_code) do nothing;

insert into group_memberships (group_id, participant, role, status)
select group_id, 'admin', 'admin', 'active'
from polla_groups
where invite_code = 'EXE2'
on conflict (group_id, participant) do nothing;

insert into group_memberships (group_id, participant, role, status)
select group_id, participant, 'player', 'active'
from polla_groups
cross join users
where invite_code = 'EXE2'
  and participant <> 'admin'
on conflict (group_id, participant) do nothing;

update ranking
set group_id = (select group_id from polla_groups where invite_code = 'EXE2')
where group_id is null
  and exists (select 1 from polla_groups where invite_code = 'EXE2');

update detail
set group_id = (select group_id from polla_groups where invite_code = 'EXE2')
where group_id is null
  and exists (select 1 from polla_groups where invite_code = 'EXE2');

alter table ranking drop constraint if exists ranking_pkey;
alter table ranking add primary key (group_id, participant);

alter table users enable row level security;
alter table polla_groups enable row level security;
alter table group_memberships enable row level security;
alter table matches enable row level security;
alter table predictions enable row level security;
alter table group_picks enable row level security;
alter table final_picks enable row level security;
alter table results enable row level security;
alter table audit_log enable row level security;
alter table settings enable row level security;
alter table ranking enable row level security;
alter table detail enable row level security;
