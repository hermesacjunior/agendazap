-- Resumo diario opcional: o dono recebe os compromissos do dia por e-mail
-- e/ou WhatsApp, no horario escolhido.

alter table public.users
  add column if not exists daily_digest_enabled boolean not null default false,
  add column if not exists daily_digest_hour integer not null default 7,
  add column if not exists daily_digest_email boolean not null default true,
  add column if not exists daily_digest_whatsapp boolean not null default false,
  add column if not exists daily_digest_last_sent varchar(10);
