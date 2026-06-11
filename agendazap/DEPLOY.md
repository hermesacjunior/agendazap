# Deploy AgendaZap

Dominio principal: `https://www.agendazapuap.com.br`
API: `https://api.agendazapuap.com.br`

## 1. Supabase

1. Crie um projeto no Supabase.
2. Em SQL Editor, execute `supabase/migrations/001_initial_schema.sql`.
3. Ative Auth por email e configure a URL do site como `https://www.agendazapuap.com.br`.
4. Copie `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` e a connection string PostgreSQL.
5. Use a connection string async no backend: `postgresql+asyncpg://...`.

## 2. Railway backend

1. Crie um projeto Railway apontando para este repositorio.
2. Configure o start command do `railway.json`.
3. Adicione as variaveis:
   - `APP_URL=https://www.agendazapuap.com.br`
   - `API_URL=https://api.agendazapuap.com.br`
   - `APP_ENV=production`
   - `ALLOWED_ORIGINS=https://www.agendazapuap.com.br,https://agendazapuap.com.br,https://api.agendazapuap.com.br`
   - `ALLOWED_HOSTS=agendazapuap.com.br,www.agendazapuap.com.br,api.agendazapuap.com.br`
   - `COOKIE_SECURE=true`
   - `FORCE_HTTPS=true`
   - `DATABASE_URL`, `JWT_SECRET`, Supabase, Resend, Stripe e WhatsApp.
4. Antes de abrir ao publico, rode `python scripts/check_env.py`.
5. Gere um dominio no Railway para o servico.
6. Em DNS, crie `api.agendazapuap.com.br` como CNAME para o dominio informado pelo Railway.

## 3. Vercel frontend

O projeto atual ainda e server-rendered FastAPI. O `vercel.json` encaminha as rotas do app para a API no Railway ate existir um frontend Vite/React separado.

1. Crie um projeto na Vercel apontando para este repositorio.
2. Configure o dominio `www.agendazapuap.com.br` e redirecione o dominio raiz para `www`.
3. Configure:
   - `VITE_APP_URL=https://www.agendazapuap.com.br`
   - `VITE_API_URL=https://api.agendazapuap.com.br`
   - `NODE_ENV=production`
4. Em DNS, aponte o dominio raiz e `www` para a Vercel conforme instrucoes da Vercel.

## 4. SSL e HTTPS

- Vercel e Railway emitem SSL automaticamente.
- Mantenha `FORCE_HTTPS=true` no Railway.
- O app envia HSTS quando HTTPS esta ativo.
- Nunca use chaves em query string, HTML, JavaScript publico ou logs.

## 5. Stripe

Webhook endpoint de producao:

`https://api.agendazapuap.com.br/webhooks/stripe`

Eventos:

- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Depois de criar o webhook, copie o `STRIPE_WEBHOOK_SECRET` para o Railway.

## 6. Checklist antes de abrir ao publico

- `.env` nao versionado.
- `DATABASE_URL` aponta para Supabase/Postgres, nao banco local.
- `JWT_SECRET` longo e aleatorio.
- `ALLOWED_ORIGINS` e `ALLOWED_HOSTS` restritos aos dominios oficiais `www` e `api`.
- Logs nao exibem tokens, senhas, cookies ou chaves.
- Stripe em modo live somente depois de testar checkout e webhook.
- Resend com dominio verificado.
- Backups do Supabase ativados.
