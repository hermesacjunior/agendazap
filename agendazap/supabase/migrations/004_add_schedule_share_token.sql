-- share_token: permite compartilhar uma visualizacao read-only de uma agenda
-- especifica (somente disponibilidade, sem dados dos clientes). Nulo = privada.

alter table public.schedules
  add column if not exists share_token varchar(64);

create index if not exists idx_schedules_share_token
  on public.schedules (share_token);
