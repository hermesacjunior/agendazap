"""Validacao de e-mail no cadastro.

Politica (apertada por causa de abuso/bots): allowlist estrita — somente
Gmail, Hotmail e Outlook (incluindo variantes regionais e a familia Microsoft
live/msn). Qualquer outro dominio (descartaveis como mailinator/immenseignite,
iCloud, dominios proprios) e recusado.
"""

import re

# Formato basico (RFC-lite): suficiente para o cadastro, o envio real confirma.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})$")

# Allowlist: SOMENTE estes provedores podem se cadastrar.
#   Google  -> gmail / googlemail
#   Hotmail -> hotmail.* (com variantes regionais comuns no Brasil)
#   Outlook -> outlook.* + familia Microsoft (live, msn)
ALLOWED_DOMAINS = {
    # Google
    "gmail.com", "googlemail.com",
    # Hotmail
    "hotmail.com", "hotmail.com.br", "hotmail.co.uk", "hotmail.fr",
    "hotmail.es", "hotmail.it", "hotmail.de",
    # Outlook
    "outlook.com", "outlook.com.br", "outlook.es", "outlook.fr",
    "outlook.pt", "outlook.it", "outlook.de",
    # Familia Microsoft (mesmas contas Hotmail/Outlook)
    "live.com", "live.com.br", "live.com.mx", "live.com.pt",
    "live.co.uk", "live.fr", "msn.com",
}


def _domain_of(email: str) -> str:
    match = _EMAIL_RE.match((email or "").strip().lower())
    return match.group(1) if match else ""


def is_valid_email_format(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip().lower()))


def is_allowed_email(email: str) -> bool:
    return _domain_of(email) in ALLOWED_DOMAINS


def validate_signup_email(email: str) -> tuple[bool, str | None]:
    """Retorna (ok, mensagem_de_erro). Mensagem em pt-BR para exibir no form."""
    domain = _domain_of(email)
    if not domain:
        return False, "Informe um e-mail válido."
    if domain not in ALLOWED_DOMAINS:
        return False, (
            "No momento aceitamos apenas e-mails Gmail, Hotmail ou Outlook. "
            "Cadastre-se com um desses provedores."
        )
    return True, None
