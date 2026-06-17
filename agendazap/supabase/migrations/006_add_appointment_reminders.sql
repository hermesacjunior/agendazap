-- Lembrete por agendamento: o cliente recebe um aviso X horas antes (opt-in).

alter table public.users
  add column if not exists reminder_enabled boolean not null default false,
  add column if not exists reminder_hours integer not null default 24,
  add column if not exists reminder_email boolean not null default true,
  add column if not exists reminder_whatsapp boolean not null default false;

alter table public.bookings
  add column if not exists reminder_sent boolean not null default false;
