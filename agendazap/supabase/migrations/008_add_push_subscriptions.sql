-- Inscricoes de Web Push (notificacoes nativas no PWA instalado).
-- Um usuario pode ter varios dispositivos. Endpoints expirados sao removidos
-- automaticamente pelo backend ao receber 404/410.

create table if not exists public.push_subscriptions (
  id text primary key,
  user_id text not null references public.users(id) on delete cascade,
  endpoint text not null unique,
  p256dh text not null,
  auth text not null,
  created_at timestamptz default now()
);

create index if not exists ix_push_subscriptions_user_id on public.push_subscriptions (user_id);
