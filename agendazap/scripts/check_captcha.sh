#!/usr/bin/env bash
# Verifica se o captcha Turnstile esta ATIVO e barrando no cadastro.
# Uso: bash scripts/check_captcha.sh [BASE_URL]
# (curl -k por causa da interceptacao de TLS no ambiente do dev; o alvo e HTTPS.)
set -u
BASE="${1:-https://www.agendazapuap.com.br}"
echo "Alvo: $BASE"

PAGE=$(curl -sk "$BASE/auth/register")
if echo "$PAGE" | grep -q "cf-turnstile"; then
  echo "PASS  widget Turnstile presente na pagina de cadastro"
else
  echo "FAIL  widget ausente -> TURNSTILE_SITE_KEY/SECRET_KEY ainda nao setados (captcha OFF)."
  echo "      Configure as duas variaveis no Railway e rode de novo."
  exit 1
fi

# POST de cadastro SEM token de captcha -> deve ser barrado pelo servidor.
JAR=$(mktemp)
curl -sk -c "$JAR" "$BASE/auth/register" -o /dev/null
C=$(awk '/csrf_token/{print $7}' "$JAR")
R=$(curl -sk -b "$JAR" -X POST "$BASE/auth/register" \
  --data-urlencode "name=Captcha Check" \
  --data-urlencode "email=captcha.check@gmail.com" \
  --data-urlencode "password=senha12345" \
  --data-urlencode "csrf_token=$C")
rm -f "$JAR"

if echo "$R" | grep -q "Recarregue a"; then
  echo "PASS  cadastro SEM captcha foi barrado (verificacao server-side ativa)"
  echo "OK: captcha ativo e barrando bots."
else
  echo "FAIL  cadastro sem captcha NAO foi barrado. Trecho da resposta:"
  echo "$R" | grep -oiE "alert-error[^<]*|dashboard" | head -1
  exit 1
fi
