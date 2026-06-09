# Stripe - AgendaZap

Use `https://agendazapuap.com.br` como dominio publico do checkout.

## Variaveis de ambiente

Configure no ambiente de producao:

```env
APP_URL=https://agendazapuap.com.br
ALLOWED_ORIGINS=https://agendazapuap.com.br,https://www.agendazapuap.com.br,https://api.agendazapuap.com.br

STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_BASIC_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...
```

Nao envie esses valores reais para o Git.

## URLs usadas pelo app

- Checkout sucesso: `https://agendazapuap.com.br/plans/success?session_id={CHECKOUT_SESSION_ID}`
- Checkout cancelado: `https://agendazapuap.com.br/plans/`
- Portal do cliente: retorna para `https://agendazapuap.com.br/plans/`
- Webhook Stripe: `https://agendazapuap.com.br/webhooks/stripe`

O `vercel.json` da raiz encaminha `/plans/*`, `/webhooks/*`, `/auth/*`, `/admin/*`, `/static/*` e `/b/*` para `https://api.agendazapuap.com.br`, onde o FastAPI roda.

## Eventos do webhook

Configure no painel da Stripe os eventos:

- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Em producao, o endpoint exige `STRIPE_WEBHOOK_SECRET`; sem ele, o webhook retorna erro em vez de aceitar eventos sem assinatura.
