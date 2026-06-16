# AgendaZap no Railway

Este fluxo provisiona o AgendaZap, PostgreSQL, Redis e Evolution API sem salvar
segredos no repositorio.

## 1. Login manual

No PowerShell, a CLI instalada por npm deve ser chamada como `railway.cmd`
quando a execucao de scripts `.ps1` estiver bloqueada:

```powershell
railway.cmd login
```

O comando abre o navegador para autenticar. Depois, volte ao terminal.

## 2. Provisionar os servicos

Execute a partir da pasta interna `agendazap`:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\deploy\railway\setup.ps1
```

O `Bypass` vale somente para esse processo e nao altera a politica permanente
do Windows.

O script cria, caso ainda nao existam:

- `Postgres`
- `Redis`
- `evolution-api`, usando `evoapicloud/evolution-api:v2.3.7`
- `agendazap`
- volume da Evolution montado em `/evolution/instances`

A chave da Evolution e solicitada com entrada oculta e enviada diretamente para
as variaveis `AUTHENTICATION_API_KEY` e `EVOLUTION_API_KEY` no Railway.

## 3. Dominios e URLs

No Railway, gere um dominio publico para `evolution-api`. Depois configure:

```powershell
railway.cmd variable set --service evolution-api "SERVER_URL=https://SEU-DOMINIO-EVOLUTION"
railway.cmd variable set --service agendazap "EVOLUTION_API_URL=https://SEU-DOMINIO-EVOLUTION"
```

Use o dominio sem barra no final. O dominio publico do AgendaZap deve apontar
para a porta exposta pelo `$PORT` do Railway.

## 4. Variaveis do AgendaZap

Configure no servico `agendazap` as variaveis exigidas por `.env.example`. Para
usar o PostgreSQL provisionado pelo Railway:

```powershell
railway.cmd variable set --service agendazap 'DATABASE_URL=postgresql+asyncpg://${{Postgres.PGUSER}}:${{Postgres.PGPASSWORD}}@${{Postgres.PGHOST}}:${{Postgres.PGPORT}}/${{Postgres.PGDATABASE}}'
```

Defina tambem `JWT_SECRET`, `SECRET_KEY`, Supabase, Stripe, email e as URLs
publicas aplicaveis. Em `ALLOWED_HOSTS`, inclua `*.railway.internal` para que o
healthcheck privado da Railway passe pelo `TrustedHostMiddleware`. Nao coloque
valores reais em arquivos versionados.

## 5. Deploy

Ainda na pasta interna:

```powershell
railway.cmd up --service agendazap --environment production
railway.cmd service redeploy --service evolution-api --environment production
```

Verifique o AgendaZap em `/health` e acompanhe falhas com:

```powershell
railway.cmd logs --service agendazap
railway.cmd logs --service evolution-api
```
