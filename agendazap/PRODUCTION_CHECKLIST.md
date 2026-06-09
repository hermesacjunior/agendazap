# Checklist de Producao - AgendaZap

## Segredos e arquivos locais

- Nunca publicar `.env`, banco `.db`, logs ou `venv`.
- Usar variaveis de ambiente no provedor de hospedagem.
- Trocar `SECRET_KEY` por uma chave longa e aleatoria antes de colocar `APP_ENV=production`.
- Configurar `JWT_SECRET` e `SECRET_KEY` com valores diferentes, longos e aleatorios.
- Rotacionar qualquer chave que tenha sido exposta em chat, print, log ou Git.

## Variaveis obrigatorias

```env
APP_ENV=production
APP_URL=https://seudominio.com
ALLOWED_ORIGINS=https://seudominio.com
ALLOWED_HOSTS=seudominio.com,www.seudominio.com
COOKIE_SECURE=true
FORCE_HTTPS=true
SECRET_KEY=chave-longa-aleatoria
JWT_SECRET=outra-chave-longa-aleatoria
DATABASE_URL=postgresql+asyncpg://usuario:senha@host:5432/agendazap
```

## Banco de dados

- Usar PostgreSQL em producao.
- Fazer backup automatico diario.
- Nao usar `agendazap.db` em producao.
- Criar migracoes antes de alterar schema em producao.
- Executar `supabase/migrations/001_initial_schema.sql` no PostgreSQL antes do primeiro deploy.
- Rodar `python scripts/check_env.py` e corrigir qualquer erro antes de publicar.

## Stripe

- Configurar Price IDs recorrentes para Basic e Pro.
- Configurar webhook em `https://seudominio.com/webhooks/stripe`.
- Eventos:
  - `checkout.session.completed`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`

## Email

- Usar dominio verificado no Resend para `FROM_EMAIL`.
- Nao usar remetente de dominio nao verificado.

## Servidor

- Rodar atras de proxy HTTPS.
- Nao expor portas internas de banco, Redis, Evolution ou containers.
- Logs devem ficar privados.
- Atualizar dependencias periodicamente.

## Seguranca aplicada no app

- CORS restrito por `ALLOWED_ORIGINS`.
- Hosts restritos por `ALLOWED_HOSTS`.
- Cookies `HttpOnly`, `SameSite=Lax` e `Secure` em HTTPS.
- Protecao basica contra POST de origem externa.
- Rate limit simples em login, cadastro e criacao de agendamento.
- Headers de seguranca HTTP.
- CSRF em formularios web autenticados e publicos.
- Webhook Stripe exige assinatura em producao.
- Paginas autenticadas enviam `Cache-Control: no-store`.
