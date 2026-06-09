# Deploy HostGator - AgendaZap

AgendaZap e um app FastAPI/ASGI. Em HostGator, confirme primeiro qual ambiente voce contratou:

- VPS/dedicado com SSH: recomendado para FastAPI.
- cPanel compartilhado: normalmente usa Passenger/WSGI; FastAPI pode exigir adaptador ASGI->WSGI ou outro plano com suporte a app Python.

## Recomendado: VPS ou cPanel com acesso SSH

1. Aponte o dominio `agendazapuap.com.br` para o servidor.
2. Crie um banco PostgreSQL gerenciado ou no proprio servidor.
3. Configure as variaveis de ambiente de producao:

```env
APP_URL=https://agendazapuap.com.br
API_URL=https://agendazapuap.com.br
APP_ENV=production
ALLOWED_ORIGINS=https://agendazapuap.com.br,https://www.agendazapuap.com.br
ALLOWED_HOSTS=agendazapuap.com.br,www.agendazapuap.com.br
COOKIE_SECURE=true
FORCE_HTTPS=true
DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:5432/DBNAME
JWT_SECRET=<valor-longo-aleatorio>
SECRET_KEY=<valor-longo-aleatorio>
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_BASIC_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...
RESEND_API_KEY=re_...
FROM_EMAIL=AgendaZap <noreply@agendazapuap.com.br>
EVOLUTION_API_URL=https://...
EVOLUTION_API_KEY=...
```

4. Instale dependencias:

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

5. Crie o schema do banco executando `supabase/migrations/001_initial_schema.sql`.
6. Valide as variaveis:

```bash
python scripts/check_env.py
```

7. Rode o app com um process manager:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

8. Configure proxy reverso HTTPS do Apache/Nginx/cPanel para `127.0.0.1:8000`.
9. Teste:

```bash
curl https://agendazapuap.com.br/health
```

## Stripe

Webhook:

```text
https://agendazapuap.com.br/webhooks/stripe
```

Eventos:

- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

## cPanel compartilhado

Se o painel oferecer apenas Passenger/WSGI, nao suba direto sem validar suporte a ASGI. FastAPI nao e WSGI puro. Nesse caso, escolha uma das opcoes:

- migrar o backend para VPS/servico Python com ASGI;
- manter HostGator para DNS/site estatico e hospedar backend em Railway/Render/Fly;
- usar adaptador ASGI->WSGI somente se o cPanel permitir instalar dependencias e a carga for baixa.

## Dados pessoais

- Nunca envie `.env`, `*.db`, logs ou backups para o Git.
- Ative backup automatico do banco.
- Restrinja acesso ao banco por IP quando possivel.
- Use HTTPS obrigatorio.
- Rotacione `JWT_SECRET`, `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` se algum valor for exposto.
