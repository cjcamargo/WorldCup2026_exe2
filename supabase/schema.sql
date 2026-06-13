create table if not exists users (
  participant text primary key,
  pin_hash text not null,
  role text not null default 'player',
  active boolean not null default true
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
  participant text not null references users(participant),
  match_id text not null references matches(match_id),
  team_a text not null,
  team_b text not null,
  goals_a_pred int,
  goals_b_pred int,
  updated_at timestamptz,
  primary key (participant, match_id)
);

create table if not exists group_picks (
  participant text not null references users(participant),
  "group" text not null,
  first text,
  second text,
  third text,
  updated_at timestamptz,
  primary key (participant, "group")
);

create table if not exists final_picks (
  participant text primary key references users(participant),
  champion text,
  runner_up text,
  third_place text,
  updated_at timestamptz
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
);

create table if not exists settings (
  key text primary key,
  value text
);

create table if not exists ranking (
  participant text primary key,
  points int not null default 0,
  rank int
);

create table if not exists detail (
  id bigserial primary key,
  participant text,
  match_id text,
  team_a text,
  team_b text,
  pred_score text,
  real_score text,
  points int
);

alter table users enable row level security;
alter table matches enable row level security;
alter table predictions enable row level security;
alter table group_picks enable row level security;
alter table final_picks enable row level security;
alter table results enable row level security;
alter table audit_log enable row level security;
alter table settings enable row level security;
alter table ranking enable row level security;
alter table detail enable row level security;
