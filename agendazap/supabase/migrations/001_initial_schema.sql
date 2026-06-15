create extension if not exists "pgcrypto";

-- Native enum types expected by the SQLAlchemy models (SAEnum(PlanType) / SAEnum(BookingStatus)).
-- Without these the ORM emits casts like `status = $1::bookingstatus`, which fail against varchar columns.
do $$ begin
  create type plantype as enum ('free', 'basic', 'pro');
exception when duplicate_object then null; end $$;

do $$ begin
  create type bookingstatus as enum ('pending', 'confirmed', 'cancelled', 'completed');
exception when duplicate_object then null; end $$;

create table if not exists public.users (
  id varchar primary key default gen_random_uuid()::text,
  name varchar(100) not null,
  email varchar(200) not null unique,
  hashed_password varchar(200) not null,
  whatsapp varchar(20),
  slug varchar(50) not null unique,
  bio text,
  is_active boolean not null default true,
  plan plantype not null default 'free',
  stripe_customer_id varchar(100),
  stripe_subscription_id varchar(100),
  evolution_instance varchar(100),
  whatsapp_connected boolean not null default false,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists public.schedules (
  id varchar primary key default gen_random_uuid()::text,
  user_id varchar not null references public.users(id) on delete cascade,
  name varchar(100) not null default 'Minha Agenda',
  slot_duration integer not null default 60 check (slot_duration between 15 and 240),
  buffer_time integer not null default 0 check (buffer_time between 0 and 120),
  max_advance_days integer not null default 30 check (max_advance_days between 1 and 365),
  is_active boolean not null default true,
  weekly_availability jsonb not null default '{}'::jsonb,
  blocked_dates jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now(),
  updated_at timestamptz
);

create table if not exists public.bookings (
  id varchar primary key default gen_random_uuid()::text,
  user_id varchar not null references public.users(id) on delete cascade,
  schedule_id varchar not null references public.schedules(id) on delete cascade,
  client_name varchar(100) not null,
  client_email varchar(200) not null,
  client_whatsapp varchar(20),
  client_notes text,
  start_datetime timestamptz not null,
  end_datetime timestamptz not null,
  status bookingstatus not null default 'confirmed',
  whatsapp_sent_admin boolean not null default false,
  whatsapp_sent_client boolean not null default false,
  email_sent_admin boolean not null default false,
  email_sent_client boolean not null default false,
  created_at timestamptz not null default now(),
  check (end_datetime > start_datetime)
);

create table if not exists public.plans (
  id varchar primary key default gen_random_uuid()::text,
  name varchar(50) not null,
  slug varchar(20) not null unique,
  price_brl double precision not null default 0,
  stripe_price_id varchar(100),
  max_bookings_month integer not null default 10,
  max_schedules integer not null default 1,
  whatsapp_notifications boolean not null default false,
  email_notifications boolean not null default true,
  custom_slug boolean not null default false,
  features jsonb not null default '[]'::jsonb,
  is_active boolean not null default true,
  created_at timestamptz not null default now()
);

create unique index if not exists users_email_lower_idx on public.users (lower(email));
create unique index if not exists users_slug_idx on public.users (slug);
create index if not exists schedules_user_active_idx on public.schedules (user_id, is_active);
create index if not exists bookings_user_status_start_idx on public.bookings (user_id, status, start_datetime);
create index if not exists bookings_schedule_range_idx on public.bookings (schedule_id, start_datetime, end_datetime);
create unique index if not exists bookings_active_slot_idx
on public.bookings (schedule_id, start_datetime)
where status <> 'cancelled'::bookingstatus;

insert into public.plans (
  slug,
  name,
  price_brl,
  max_bookings_month,
  max_schedules,
  email_notifications,
  whatsapp_notifications,
  custom_slug,
  features
) values
  ('free', 'Free', 0, 1, 1, true, false, false, '["1 agendamento gratis", "Notificacao por email"]'::jsonb),
  ('basic', 'Basic', 49, 100, 1, true, false, true, '["100 agendamentos por mes", "Notificacao por email", "Link personalizado"]'::jsonb),
  ('pro', 'Pro', 99, 1000000, 5, true, true, true, '["Agendamentos ilimitados", "Notificacao WhatsApp", "Multiplas agendas"]'::jsonb)
on conflict (slug) do update set
  name = excluded.name,
  price_brl = excluded.price_brl,
  max_bookings_month = excluded.max_bookings_month,
  max_schedules = excluded.max_schedules,
  email_notifications = excluded.email_notifications,
  whatsapp_notifications = excluded.whatsapp_notifications,
  custom_slug = excluded.custom_slug,
  features = excluded.features;
