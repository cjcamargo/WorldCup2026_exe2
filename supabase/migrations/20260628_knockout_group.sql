begin;

alter table polla_groups
  add column if not exists competition_mode text not null default 'full';

alter table polla_groups drop constraint if exists polla_groups_competition_mode_check;
alter table polla_groups add constraint polla_groups_competition_mode_check
  check (competition_mode in ('group_stage', 'knockout', 'full'));

update polla_groups set competition_mode = 'group_stage' where invite_code = 'EXE2';

insert into polla_groups (name, invite_code, created_by, competition_mode)
select 'Exe2 Knockout', 'EXE2KO', 'admin', 'knockout'
where exists (select 1 from users where participant = 'admin')
on conflict (invite_code) do update
set name = excluded.name, competition_mode = excluded.competition_mode, active = true;

insert into group_memberships (group_id, participant, role, status)
select group_id, 'admin', 'admin', 'active'
from polla_groups where invite_code = 'EXE2KO'
on conflict (group_id, participant) do update set role = 'admin', status = 'active';

insert into group_memberships (group_id, participant, role, status)
select group_id, users.participant, 'player', 'active'
from polla_groups
join users on users.participant in ('CarlosF', 'Alex', 'Oscar', 'Charlie', 'Eduard')
where invite_code = 'EXE2KO'
on conflict (group_id, participant) do update set role = 'player', status = 'active';

alter table predictions add column if not exists group_id uuid references polla_groups(group_id) on delete cascade;
alter table predictions add column if not exists qualified_team_pred text;
alter table group_picks add column if not exists group_id uuid references polla_groups(group_id) on delete cascade;
alter table final_picks add column if not exists group_id uuid references polla_groups(group_id) on delete cascade;
alter table audit_log add column if not exists group_id uuid references polla_groups(group_id) on delete set null;

update predictions set group_id = (select group_id from polla_groups where invite_code = 'EXE2') where group_id is null;
update group_picks set group_id = (select group_id from polla_groups where invite_code = 'EXE2') where group_id is null;
update final_picks set group_id = (select group_id from polla_groups where invite_code = 'EXE2') where group_id is null;
update audit_log set group_id = (select group_id from polla_groups where invite_code = 'EXE2') where group_id is null;

alter table predictions drop constraint if exists predictions_pkey;
alter table predictions alter column group_id set not null;
alter table predictions add primary key (group_id, participant, match_id);

alter table group_picks drop constraint if exists group_picks_pkey;
alter table group_picks alter column group_id set not null;
alter table group_picks add primary key (group_id, participant, "group");

alter table final_picks drop constraint if exists final_picks_pkey;
alter table final_picks alter column group_id set not null;
alter table final_picks add primary key (group_id, participant);

alter table results add column if not exists final_goals_a int;
alter table results add column if not exists final_goals_b int;
alter table results add column if not exists penalties_a int;
alter table results add column if not exists penalties_b int;
alter table results add column if not exists qualified_team text;
alter table results add column if not exists decision text;

create index if not exists predictions_group_participant_idx on predictions (group_id, participant);
create index if not exists group_picks_group_participant_idx on group_picks (group_id, participant);
create index if not exists final_picks_group_participant_idx on final_picks (group_id, participant);
create index if not exists audit_log_group_detected_idx on audit_log (group_id, detected_at);

insert into matches (match_id, phase, team_a, team_b, kickoff_at, status) values
('M073','Round of 32','South Africa','Canada','2026-06-28T14:00:00-05:00','scheduled'),
('M074','Round of 32','Germany','Paraguay','2026-06-29T15:30:00-05:00','scheduled'),
('M075','Round of 32','Netherlands','Morocco','2026-06-29T20:00:00-05:00','scheduled'),
('M076','Round of 32','Brazil','Japan','2026-06-29T12:00:00-05:00','scheduled'),
('M077','Round of 32','France','Sweden','2026-06-30T16:00:00-05:00','scheduled'),
('M078','Round of 32','Cote d''Ivoire','Norway','2026-06-30T12:00:00-05:00','scheduled'),
('M079','Round of 32','Mexico','Ecuador','2026-06-30T20:00:00-05:00','scheduled'),
('M080','Round of 32','England','DR Congo','2026-07-01T11:00:00-05:00','scheduled'),
('M081','Round of 32','United States','Bosnia and Herzegovina','2026-07-01T19:00:00-05:00','scheduled'),
('M082','Round of 32','Belgium','Senegal','2026-07-01T15:00:00-05:00','scheduled'),
('M083','Round of 32','Portugal','Croatia','2026-07-02T18:00:00-05:00','scheduled'),
('M084','Round of 32','Spain','Austria','2026-07-02T14:00:00-05:00','scheduled'),
('M085','Round of 32','Switzerland','Algeria','2026-07-02T22:00:00-05:00','scheduled'),
('M086','Round of 32','Argentina','Cabo Verde','2026-07-03T17:00:00-05:00','scheduled'),
('M087','Round of 32','Colombia','Ghana','2026-07-03T20:30:00-05:00','scheduled'),
('M088','Round of 32','Australia','Egypt','2026-07-03T13:00:00-05:00','scheduled'),
('M089','Round of 16','Winner M074','Winner M077','2026-07-04T16:00:00-05:00','scheduled'),
('M090','Round of 16','Winner M073','Winner M075','2026-07-04T12:00:00-05:00','scheduled'),
('M091','Round of 16','Winner M076','Winner M078','2026-07-05T15:00:00-05:00','scheduled'),
('M092','Round of 16','Winner M079','Winner M080','2026-07-05T19:00:00-05:00','scheduled'),
('M093','Round of 16','Winner M083','Winner M084','2026-07-06T14:00:00-05:00','scheduled'),
('M094','Round of 16','Winner M081','Winner M082','2026-07-06T19:00:00-05:00','scheduled'),
('M095','Round of 16','Winner M086','Winner M088','2026-07-07T11:00:00-05:00','scheduled'),
('M096','Round of 16','Winner M085','Winner M087','2026-07-07T15:00:00-05:00','scheduled'),
('M097','Quarter-finals','Winner M089','Winner M090','2026-07-09T15:00:00-05:00','scheduled'),
('M098','Quarter-finals','Winner M093','Winner M094','2026-07-10T14:00:00-05:00','scheduled'),
('M099','Quarter-finals','Winner M091','Winner M092','2026-07-11T16:00:00-05:00','scheduled'),
('M100','Quarter-finals','Winner M095','Winner M096','2026-07-11T20:00:00-05:00','scheduled'),
('M101','Semi-finals','Winner M097','Winner M098','2026-07-14T14:00:00-05:00','scheduled'),
('M102','Semi-finals','Winner M099','Winner M100','2026-07-15T14:00:00-05:00','scheduled'),
('M103','Third place','Loser M101','Loser M102','2026-07-18T16:00:00-05:00','scheduled'),
('M104','Final','Winner M101','Winner M102','2026-07-19T14:00:00-05:00','scheduled')
on conflict (match_id) do update set
  phase = excluded.phase,
  team_a = excluded.team_a,
  team_b = excluded.team_b,
  kickoff_at = excluded.kickoff_at;

insert into settings (key, value) values ('final_picks_closed_EXE2KO', 'False')
on conflict (key) do nothing;

commit;
