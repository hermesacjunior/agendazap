"""Camada de protecao contra acessos/trafego suspeito.

Defesa em profundidade, em memoria (o app roda em container unico de longa
duracao no Railway, entao o estado persiste entre requisicoes):

  - Banimento temporario de IPs.
  - Bloqueio de scanners de vulnerabilidade / scrapers por User-Agent.
  - Honeypot de caminhos que so um scanner acessaria (.env, .git, *.php...).
  - Limite global de requisicoes por IP (anti-flood/scraping).
  - Trava de forca-bruta de login (por conta e por IP).

Saude (/health) e webhooks (Stripe) NUNCA passam por aqui — quem chama o guard
ja exclui esses caminhos.
"""

import re
import time
from typing import Optional

# ───────── Parametros (ajustaveis) ─────────
GLOBAL_IP_MAX = 300          # requisicoes por IP...
GLOBAL_IP_WINDOW = 60        # ...a cada 60s (acima disso = flood)
BAN_FLOOD_SECONDS = 10 * 60

BAN_SCANNER_SECONDS = 60 * 60
BAN_HONEYPOT_SECONDS = 60 * 60

LOGIN_FAIL_MAX = 6           # falhas para a MESMA conta+IP...
LOGIN_FAIL_WINDOW = 15 * 60  # ...na janela
LOGIN_BLOCK_SECONDS = 15 * 60

IP_LOGIN_FAIL_MAX = 30       # falhas de login do IP (qualquer conta) = stuffing
BAN_STUFFING_SECONDS = 30 * 60

# User-Agents de ferramentas de ataque/scraping agressivo. Conservador de
# proposito: navegadores e integracoes legitimas (Stripe, curl pontual) passam.
_SCANNER_UA = re.compile(
    r"(sqlmap|nikto|nmap|masscan|zgrab|nuclei|acunetix|nessus|openvas|wpscan|"
    r"dirbuster|gobuster|feroxbuster|ffuf|fimap|hydra|medusa|metasploit|"
    r"havij|jorgee|netsparker|qualys|w3af|skipfish|arachni|zmeu|morfeus|"
    r"semrushbot|ahrefsbot|mj12bot|dotbot|petalbot|bytespider|dataforseo)",
    re.I,
)

# Caminhos que o app NUNCA serve — acesso = sondagem. Ban imediato.
_HONEYPOT = re.compile(
    r"(?:^|/)(?:\.env|\.git|\.svn|\.hg|\.aws|\.ssh|\.config|\.vscode|\.idea|"
    r"wp-admin|wp-login|wp-content|wp-includes|xmlrpc|phpmyadmin|adminer|"
    r"server-status|actuator|cgi-bin|composer\.json|\.htaccess|\.htpasswd|"
    r"id_rsa|credentials|secrets?)",
    re.I,
)
_BAD_SUFFIX = (".php", ".asp", ".aspx", ".jsp", ".sql", ".bak", ".cgi", ".env", ".old")

# ───────── Estado em memoria ─────────
_BANNED: dict[str, tuple[float, str]] = {}        # ip -> (expira_em, motivo)
_REQ_HITS: dict[str, list[float]] = {}            # ip -> timestamps (janela global)
_LOGIN_FAILS: dict[str, list[float]] = {}         # "ip|email" -> timestamps
_IP_LOGIN_FAILS: dict[str, list[float]] = {}      # ip -> timestamps
_LAST_SWEEP = 0.0


def client_ip(request) -> str:
    """IP real do cliente atras do proxy do Railway/Cloudflare."""
    cf = request.headers.get("cf-connecting-ip")
    if cf:
        return cf.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _recent(stamps: list[float], window: float, now: float) -> list[float]:
    return [s for s in stamps if now - s < window]


def _sweep(now: float) -> None:
    """Limpeza periodica para o estado nao crescer sem limite."""
    global _LAST_SWEEP
    if now - _LAST_SWEEP < 300:
        return
    _LAST_SWEEP = now
    for ip, (exp, _) in list(_BANNED.items()):
        if exp <= now:
            del _BANNED[ip]
    for store, window in (
        (_REQ_HITS, GLOBAL_IP_WINDOW),
        (_LOGIN_FAILS, LOGIN_FAIL_WINDOW),
        (_IP_LOGIN_FAILS, LOGIN_FAIL_WINDOW),
    ):
        for k, stamps in list(store.items()):
            kept = _recent(stamps, window, now)
            if kept:
                store[k] = kept
            else:
                del store[k]


# ───────── Banimento ─────────
def ban_ip(ip: str, seconds: int, reason: str) -> None:
    if ip and ip != "unknown":
        _BANNED[ip] = (time.time() + seconds, reason)


def banned_ttl(ip: str) -> Optional[int]:
    """Segundos restantes de ban, ou None se nao banido."""
    entry = _BANNED.get(ip)
    if not entry:
        return None
    exp, _ = entry
    now = time.time()
    if exp <= now:
        _BANNED.pop(ip, None)
        return None
    return int(exp - now)


# ───────── Deteccao ─────────
def is_scanner_ua(user_agent: str) -> bool:
    return bool(user_agent) and bool(_SCANNER_UA.search(user_agent))


def is_honeypot_path(path: str) -> bool:
    p = (path or "").lower()
    if _HONEYPOT.search(p):
        return True
    return p.endswith(_BAD_SUFFIX)


def over_global_limit(ip: str) -> bool:
    """Conta a requisicao e devolve True se o IP estourou o teto global."""
    now = time.time()
    _sweep(now)
    hits = _recent(_REQ_HITS.get(ip, []), GLOBAL_IP_WINDOW, now)
    hits.append(now)
    _REQ_HITS[ip] = hits
    return len(hits) > GLOBAL_IP_MAX


# ───────── Forca-bruta de login ─────────
def login_block_ttl(ip: str, email: str) -> Optional[int]:
    """Segundos restantes de bloqueio para esta conta+IP, ou None."""
    now = time.time()
    fails = _recent(_LOGIN_FAILS.get(f"{ip}|{email}", []), LOGIN_FAIL_WINDOW, now)
    if len(fails) >= LOGIN_FAIL_MAX:
        # bloqueia ate a falha mais antiga sair da janela
        return int(LOGIN_BLOCK_SECONDS - (now - min(fails)))
    return None


def record_login_failure(ip: str, email: str) -> None:
    now = time.time()
    key = f"{ip}|{email}"
    _LOGIN_FAILS[key] = _recent(_LOGIN_FAILS.get(key, []), LOGIN_FAIL_WINDOW, now) + [now]
    ipf = _recent(_IP_LOGIN_FAILS.get(ip, []), LOGIN_FAIL_WINDOW, now) + [now]
    _IP_LOGIN_FAILS[ip] = ipf
    # Muitas falhas do mesmo IP em contas diferentes = credential stuffing.
    if len(ipf) >= IP_LOGIN_FAIL_MAX:
        ban_ip(ip, BAN_STUFFING_SECONDS, "login-stuffing")


def clear_login_failures(ip: str, email: str) -> None:
    _LOGIN_FAILS.pop(f"{ip}|{email}", None)
    _IP_LOGIN_FAILS.pop(ip, None)
