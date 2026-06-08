# AgendaZap

SaaS de agendamento online para `https://www.agendazapuap.com.br`, com API em `https://api.agendazapuap.com.br`.

## Stack

- Backend: FastAPI, Jinja2 e SQLAlchemy async
- Banco: PostgreSQL/Supabase em producao
- Auth: Supabase Auth preparado, com compatibilidade temporaria para JWT local
- Email: Resend
- Pagamentos: Stripe
- WhatsApp: Evolution API para integracao futura

## Configuracao

1. Copie `.env.example` para `.env` somente no ambiente seguro.
2. Preencha `DATABASE_URL`, `JWT_SECRET`, Supabase, Resend, Stripe e WhatsApp.
3. Nunca versione `.env`, banco local, logs, cache Python ou chaves privadas.

## Rotas principais

- Site: `/auth/login`, `/auth/register`, `/admin/dashboard`, `/admin/schedule`, `/admin/bookings`, `/admin/whatsapp`, `/admin/profile`, `/plans`
- Link publico: `/b/{slug}`
- API: `/api/auth/me`, `/api/profile`, `/api/agenda`, `/api/availability`, `/api/appointments`
- Stripe webhook: `/webhooks/stripe`

## Deploy

Use `DEPLOY.md` para publicar:

- Frontend/domino principal: Vercel
- Backend/API: Railway
- Banco e Auth: Supabase

## Banco

A migration inicial fica em `supabase/migrations/001_initial_schema.sql`.
