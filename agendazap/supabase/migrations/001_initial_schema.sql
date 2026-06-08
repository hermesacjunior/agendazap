create extension if not exists "pgcrypto";

create or replace function public.set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create table if not exists public.users (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid unique references auth.users(id) on delete set null,
  email text not null unique,
  name text not null,
  phone text,
  role text not null default 'user' check (role in ('user', 'admin')),
  status text not null default 'active' check (status in ('active', 'blocked', 'deleted')),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.profiles (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null unique references public.users(id) on delete cascade,
  display_name text,
  bio text,
  whatsapp text,
  public_slug text unique,
  timezone text not null default 'America/Sao_Paulo',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.plans (
  id uuid primary key default gen_random_uuid(),
  slug text not null unique,
  name text not null,
  price_brl numeric(10,2) not null default 0,
  stripe_price_id text unique,
  max_bookings_month integer not null default 1,
  max_agendas integer not null default 1,
  email_notifications boolean not null default true,
  whatsapp_notifications boolean not null default false,
  sms_notifications boolean not null default false,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.subscriptions (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  plan_id uuid references public.plans(id) on delete set null,
  stripe_customer_id text,
  stripe_subscription_id text unique,
  status text not null default 'inactive',
  current_period_start timestamptz,
  current_period_end timestamptz,
  cancel_at_period_end boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.agendas (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  name text not null,
  slug text not null unique,
  slot_duration integer not null default 60,
  buffer_time integer not null default 0,
  max_advance_days integer not null default 30,
  timezone text not null default 'America/Sao_Paulo',
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.availability (
  id uuid primary key default gen_random_uuid(),
  agenda_id uuid not null references public.agendas(id) on delete cascade,
  weekday smallint not null check (weekday between 0 and 6),
  start_time time not null,
  end_time time not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  check (end_time > start_time)
);

create table if not exists public.appointments (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  agenda_id uuid not null references public.agendas(id) on delete cascade,
  client_name text not null,
  client_email text not null,
  client_phone text,
  client_notes text,
  start_at timestamptz not null,
  end_at timestamptz not null,
  status text not null default 'confirmed' check (status in ('pending', 'confirmed', 'cancelled', 'completed')),
  cancelled_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz,
  check (end_at > start_at)
);

create table if not exists public.public_links (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  agenda_id uuid not null references public.agendas(id) on delete cascade,
  slug text not null unique,
  url text not null,
  is_active boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.notifications (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references public.users(id) on delete cascade,
  appointment_id uuid references public.appointments(id) on delete cascade,
  channel text not null check (channel in ('email', 'sms', 'whatsapp')),
  recipient text not null,
  subject text,
  body text,
  status text not null default 'pending' check (status in ('pending', 'sent', 'failed', 'skipped')),
  provider text,
  provider_message_id text,
  error text,
  sent_at timestamptz,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create table if not exists public.whatsapp_connections (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references public.users(id) on delete cascade,
  provider text not null default 'evolution',
  instance_name text not null unique,
  phone text,
  status text not null default 'disconnected',
  connected_at timestamptz,
  last_checked_at timestamptz,
  metadata jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  deleted_at timestamptz
);

create unique index if not exists appointments_active_slot_idx
on public.appointments (agenda_id, start_at)
where status <> 'cancelled' and deleted_at is null;

create index if not exists users_email_idx on public.users (lower(email)) where deleted_at is null;
create index if not exists profiles_user_id_idx on public.profiles (user_id) where deleted_at is null;
create index if not exists agendas_user_id_idx on public.agendas (user_id) where deleted_at is null;
create index if not exists availability_agenda_weekday_idx on public.availability (agenda_id, weekday) where deleted_at is null;
create index if not exists appointments_user_status_start_idx on public.appointments (user_id, status, start_at) where deleted_at is null;
create index if not exists appointments_agenda_range_idx on public.appointments (agenda_id, start_at, end_at) where deleted_at is null;
create index if not exists subscriptions_user_id_idx on public.subscriptions (user_id) where deleted_at is null;
create index if not exists public_links_slug_idx on public.public_links (slug) where deleted_at is null;
create index if not exists notifications_user_status_idx on public.notifications (user_id, status) where deleted_at is null;
create index if not exists whatsapp_connections_user_status_idx on public.whatsapp_connections (user_id, status) where deleted_at is null;

create trigger set_users_updated_at before update on public.users for each row execute function public.set_updated_at();
create trigger set_profiles_updated_at before update on public.profiles for each row execute function public.set_updated_at();
create trigger set_plans_updated_at before update on public.plans for each row execute function public.set_updated_at();
create trigger set_subscriptions_updated_at before update on public.subscriptions for each row execute function public.set_updated_at();
create trigger set_agendas_updated_at before update on public.agendas for each row execute function public.set_updated_at();
create trigger set_availability_updated_at before update on public.availability for each row execute function public.set_updated_at();
create trigger set_appointments_updated_at before update on public.appointments for each row execute function public.set_updated_at();
create trigger set_public_links_updated_at before update on public.public_links for each row execute function public.set_updated_at();
create trigger set_notifications_updated_at before update on public.notifications for each row execute function public.set_updated_at();
create trigger set_whatsapp_connections_updated_at before update on public.whatsapp_connections for each row execute function public.set_updated_at();

insert into public.plans (slug, name, price_brl, max_bookings_month, max_agendas, email_notifications, whatsapp_notifications, sms_notifications)
values
  ('free', 'Free', 0, 1, 1, true, false, false),
  ('basic', 'Basic', 49, 100, 1, true, false, false),
  ('pro', 'Pro', 99, 1000000, 5, true, true, true)
on conflict (slug) do nothing;

alter table public.users enable row level security;
alter table public.profiles enable row level security;
alter table public.agendas enable row level security;
alter table public.availability enable row level security;
alter table public.appointments enable row level security;
alter table public.plans enable row level security;
alter table public.subscriptions enable row level security;
alter table public.public_links enable row level security;
alter table public.notifications enable row level security;
alter table public.whatsapp_connections enable row level security;
