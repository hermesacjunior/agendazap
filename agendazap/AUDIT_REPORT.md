# Auditoria de Producao - AgendaZap

## Problemas encontrados

- Defaults de ambiente usavam endereco local em codigo e documentacao.
- `.env.example` tinha placeholders de desenvolvimento e nao refletia os dominios finais.
- API JSON dedicada ainda nao existia para perfil, agenda, disponibilidade e agendamentos.
- Migration PostgreSQL/Supabase nao existia.
- Recuperacao de senha nao existia.
- Links publicos do painel eram montados a partir do host da requisicao, podendo exibir endereco local/proxy.
- `resend` estava em `requirements.txt`, mas o servico usa `httpx` diretamente.
- O projeto atual e FastAPI server-rendered, nao um frontend Vite separado.
- Arquivos locais como banco SQLite, logs e caches Python existem na maquina e nao devem ir ao deploy.
- A pasta `{app}` existe, mas esta vazia; e um artefato obsoleto local.

## Correcoes aplicadas

- `.env.example` refeito para producao com dominios oficiais, Supabase, Stripe, WhatsApp, JWT e NODE_ENV.
- Defaults de producao adicionados em `main.py`, `plans.py`, `email_service.py`, `whatsapp_service.py` e `auth_service.py`.
- `WHATSAPP_API_KEY` e `JWT_SECRET` agora sao aceitos como aliases seguros.
- Middleware de seguranca existente mantem CORS restrito, host allowlist, HTTPS, headers e rate limit.
- Criada API `/api/auth/me`, `/api/profile`, `/api/agenda`, `/api/availability` e `/api/appointments`.
- Criado suporte a validacao de Bearer token Supabase quando Supabase estiver configurado.
- Criada recuperacao de senha via Supabase Auth.
- Links publicos do painel e da API agora usam `APP_URL`.
- Criada migration `supabase/migrations/001_initial_schema.sql`.
- Criados `vercel.json`, `railway.json`, `Procfile` e `DEPLOY.md`.
- README substituido por versao objetiva de producao.

## Riscos restantes

- A migracao completa do login/cadastro para Supabase Auth ainda depende das chaves reais e da decisao final de fluxo frontend/backend.
- Evolution API precisa de endpoint publico seguro se for usada em producao.
- SQLite local deve ser abandonado em producao.
- Devem ser configurados backups, observabilidade e rotacao de chaves no provedor.
