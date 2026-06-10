#!/usr/bin/env bash
set -euo pipefail

DOMAIN="${DOMAIN:-agendazapuap.com.br}"
APP_USER="${APP_USER:-agendazap}"
APP_DIR="${APP_DIR:-/var/www/agendazap/current}"
ENV_DIR="${ENV_DIR:-/etc/agendazap}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Execute como root: sudo bash deploy/scripts/bootstrap_ubuntu_vps.sh"
  exit 1
fi

apt-get update
apt-get install -y python3 python3-venv python3-pip git nginx postgresql postgresql-contrib certbot python3-certbot-nginx

id -u "$APP_USER" >/dev/null 2>&1 || useradd --system --home /var/www/agendazap --shell /usr/sbin/nologin "$APP_USER"
mkdir -p /var/www/agendazap "$ENV_DIR" /var/log/agendazap /var/www/certbot
chown -R "$APP_USER":www-data /var/www/agendazap /var/log/agendazap
chmod 750 "$ENV_DIR"

echo "Base instalada."
echo "Proximos passos:"
echo "1. Envie o codigo para $APP_DIR"
echo "2. Crie $ENV_DIR/agendazap.env a partir de deploy/env/agendazap.env.example"
echo "3. Configure PostgreSQL e rode a migracao"
echo "4. Instale systemd/nginx conforme HOSTGATOR_DEPLOY.md"
echo "5. Emita SSL: certbot --nginx -d $DOMAIN -d www.$DOMAIN"
