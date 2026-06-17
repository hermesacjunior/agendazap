-- email_notifications: liga/desliga as notificacoes por e-mail enviadas ao
-- dono da agenda (novos agendamentos e cancelamentos). Ativo por padrao.

alter table public.users
  add column if not exists email_notifications boolean not null default true;
