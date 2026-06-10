# Deploy VPS HostGator - AgendaZap

AgendaZap e um app FastAPI/ASGI. Para producao, use uma VPS Linux com SSH. Evite cPanel compartilhado para este projeto.

Este guia assume Ubuntu 22.04/24.04, Nginx, PostgreSQL local e dominio:

- `agendazapuap.com.br`
- `www.agendazapuap.com.br`

## 1. DNS

No painel do dominio, aponte:

```text
A     @      IP_DA_VPS
A     www    IP_DA_VPS
```

A propagacao pode levar algumas horas.

## 2. Acesso inicial

Entre na VPS:

```bash
ssh root@IP_DA_VPS
```

Atualize o servidor:

```bash
apt update && apt upgrade -y
```

## 3. Instalar base do servidor

Dentro da pasta do projeto, o arquivo abaixo instala Python, Nginx, PostgreSQL e Certbot:

```bash
sudo bash deploy/scripts/bootstrap_ubuntu_vps.sh
```

Se o codigo ainda nao estiver na VPS, rode manualmente:

```bash
apt update
apt install -y python3 python3-venv python3-pip git nginx postgresql postgresql-contrib certbot python3-certbot-nginx
useradd --system --home /var/www/agendazap --shell /usr/sbin/nologin agendazap || true
mkdir -p /var/www/agendazap/current /etc/agendazap /var/log/agendazap /var/www/certbot
chown -R agendazap:www-data /var/www/agendazap /var/log/agendazap
chmod 750 /etc/agendazap
```

## 4. Enviar codigo

Recomendado via Git:

```bash
cd /var/www/agendazap
git clone https://github.com/hermesacjunior/agendazap.git current
cd current/agendazap
```

Se o repositorio for privado, configure uma chave SSH ou use deploy key.

## 5. Criar ambiente Python

```bash
cd /var/www/agendazap/current/agendazap
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

## 6. Criar banco PostgreSQL

Entre no PostgreSQL:

```bash
sudo -u postgres psql
```

Crie usuario e banco, trocando a senha:

```sql
CREATE USER agendazap WITH PASSWORD 'SENHA_FORTE_AQUI';
CREATE DATABASE agendazap OWNER agendazap;
GRANT ALL PRIVILEGES ON DATABASE agendazap TO agendazap;
\q
```

Crie as tabelas:

```bash
cd /var/www/agendazap/current/agendazap
sudo -u postgres psql -d agendazap -f supabase/migrations/001_initial_schema.sql
```

## 7. Configurar variaveis de ambiente

Crie o arquivo real:

```bash
sudo mkdir -p /etc/agendazap
sudo cp deploy/env/agendazap.env.example /etc/agendazap/agendazap.env
sudo nano /etc/agendazap/agendazap.env
sudo chmod 640 /etc/agendazap/agendazap.env
sudo chown root:www-data /etc/agendazap/agendazap.env
```

Configure pelo menos:

```env
APP_URL=https://agendazapuap.com.br
API_URL=https://agendazapuap.com.br
APP_ENV=production
ALLOWED_ORIGINS=https://agendazapuap.com.br,https://www.agendazapuap.com.br
ALLOWED_HOSTS=agendazapuap.com.br,www.agendazapuap.com.br
COOKIE_SECURE=true
FORCE_HTTPS=true
DATABASE_URL=postgresql+asyncpg://agendazap:SENHA_FORTE_AQUI@127.0.0.1:5432/agendazap
JWT_SECRET=CHAVE_LONGA_ALEATORIA_1
SECRET_KEY=CHAVE_LONGA_ALEATORIA_2
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_BASIC_PRICE_ID=price_...
STRIPE_PRO_PRICE_ID=price_...
RESEND_API_KEY=re_...
FROM_EMAIL=AgendaZap <noreply@agendazapuap.com.br>
```

Gere chaves seguras:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 8. Validar ambiente

```bash
cd /var/www/agendazap/current/agendazap
set -a
. /etc/agendazap/agendazap.env
set +a
venv/bin/python scripts/check_env.py
```

Se aparecer erro de SQLite, corrija `DATABASE_URL`. Em producao precisa ser PostgreSQL.

## 9. Instalar systemd

Copie o servico:

```bash
sudo cp deploy/systemd/agendazap.service /etc/systemd/system/agendazap.service
sudo systemctl daemon-reload
sudo systemctl enable agendazap
sudo systemctl start agendazap
sudo systemctl status agendazap
```

Logs:

```bash
journalctl -u agendazap -f
```

## 10. Instalar Nginx inicial

Antes de emitir SSL, use o proxy HTTP inicial:

```bash
sudo cp deploy/nginx/agendazap-http.conf /etc/nginx/sites-available/agendazap.conf
sudo ln -s /etc/nginx/sites-available/agendazap.conf /etc/nginx/sites-enabled/agendazap.conf
sudo nginx -t
sudo systemctl reload nginx
```

## 11. SSL HTTPS

Depois que o DNS estiver apontando para a VPS:

```bash
sudo certbot --nginx -d agendazapuap.com.br -d www.agendazapuap.com.br
```

Depois de emitir o certificado, aplique o proxy HTTPS definitivo:

```bash
sudo cp deploy/nginx/agendazap.conf /etc/nginx/sites-available/agendazap.conf
sudo nginx -t
sudo systemctl reload nginx
```

Teste renovacao:

```bash
sudo certbot renew --dry-run
```

## 12. Testes finais

```bash
curl https://agendazapuap.com.br/health
curl -I https://agendazapuap.com.br/auth/login
```

Abra no navegador:

```text
https://agendazapuap.com.br/auth/login
```

## 13. Stripe

Configure no painel Stripe:

```text
Webhook URL: https://agendazapuap.com.br/webhooks/stripe
```

Eventos:

- `checkout.session.completed`
- `customer.subscription.updated`
- `customer.subscription.deleted`

Copie o `whsec_...` para `STRIPE_WEBHOOK_SECRET`.

## 14. Rotina de atualizacao

```bash
cd /var/www/agendazap/current
git pull
cd agendazap
source venv/bin/activate
pip install -r requirements.txt
sudo systemctl restart agendazap
sudo systemctl status agendazap
```

## 15. Seguranca operacional

- Nunca coloque `.env`, `*.db`, logs ou backups no Git.
- Use senha forte no PostgreSQL.
- Ative firewall permitindo apenas SSH, HTTP e HTTPS.
- Ative backup diario do banco.
- Use acesso SSH por chave, nao senha, quando possivel.
- Mantenha `JWT_SECRET`, `SECRET_KEY`, Stripe e Resend fora do repositorio.
