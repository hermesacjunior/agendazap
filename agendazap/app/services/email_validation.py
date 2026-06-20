"""Validacao de e-mail no cadastro.

Objetivo: proteger a plataforma contra e-mails temporarios/descartaveis.
Politica: permitir os grandes provedores (Google, Hotmail/Outlook/Live, iCloud)
e qualquer dominio proprio legitimo; bloquear dominios descartaveis conhecidos
e formatos invalidos.
"""

import re

# Formato basico (RFC-lite): suficiente para o cadastro, o envio real confirma.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})$")

# Provedores explicitamente liberados (documenta a intencao do produto). Nao e
# uma allowlist exclusiva: dominios proprios tambem passam, desde que nao sejam
# descartaveis. Mantido para referencia/clareza.
ALLOWED_FREE_PROVIDERS = {
    # Google
    "gmail.com", "googlemail.com",
    # Hotmail / Outlook / Live (Microsoft)
    "hotmail.com", "hotmail.com.br", "hotmail.co.uk", "hotmail.fr", "hotmail.es",
    "outlook.com", "outlook.com.br", "outlook.es", "outlook.fr",
    "live.com", "live.com.br", "live.com.mx", "msn.com",
    # iCloud (Apple)
    "icloud.com", "me.com", "mac.com",
}

# Dominios descartaveis / temporarios conhecidos. Lista curada dos provedores
# mais comuns; o objetivo e bloquear o grosso do abuso sem MX externo.
DISPOSABLE_DOMAINS = {
    "10minutemail.com", "10minutemail.net", "20minutemail.com", "33mail.com",
    "guerrillamail.com", "guerrillamail.net", "guerrillamail.org", "guerrillamail.biz",
    "guerrillamailblock.com", "sharklasers.com", "grr.la", "spam4.me",
    "mailinator.com", "mailinator.net", "mailinator2.com", "mailnesia.com",
    "maildrop.cc", "mailcatch.com", "mailnull.com", "mintemail.com",
    "tempmail.com", "temp-mail.org", "tempmail.net", "tempmailo.com",
    "tempr.email", "tempmailaddress.com", "tempinbox.com", "throwawaymail.com",
    "throwawaymailbox.com", "trashmail.com", "trashmail.net", "trash-mail.com",
    "trashmail.de", "wegwerfmail.de", "wegwerfmail.net", "wegwerfmail.org",
    "yopmail.com", "yopmail.net", "yopmail.fr", "cool.fr.nf", "jetable.fr.nf",
    "nospam.ze.tc", "nomail.xl.cx", "mega.zik.dj", "speed.1s.fr",
    "getnada.com", "nada.email", "getairmail.com", "dispostable.com",
    "fakeinbox.com", "fakemailgenerator.com", "fake-mail.ml", "mailtemp.info",
    "emailondeck.com", "emailtemporanea.com", "emailtemporanea.net",
    "moakt.com", "moakt.cc", "moakt.ws", "tmail.ws", "tmailor.com",
    "burnermail.io", "mohmal.com", "mailpoof.com", "inboxkitten.com",
    "luxusmail.org", "mailbox.in.ua", "tafmail.com", "gufum.com",
    "dropmail.me", "10mail.org", "discard.email", "discardmail.com",
    "spambox.us", "spamgourmet.com", "anonbox.net", "antispam.de",
    "incognitomail.org", "0clickemail.com", "33m.co", "binkmail.com",
    "bobmail.info", "chacuo.net", "deadaddress.com", "despam.it",
    "spamavert.com", "spambog.com", "spambog.ru", "spamfree24.org",
    "tempemail.net", "tempemail.com", "temporaryemail.net", "temporaryinbox.com",
    "thankyou2010.com", "trbvm.com", "veryrealemail.com", "vpn.st",
    "vomoto.com", "wh4f.org", "willhackforfood.biz", "willselfdestruct.com",
    "wuzup.net", "wuzupmail.net", "xagloo.com", "yep.it", "zoemail.com",
    "harakirimail.com", "haribu.com", "hartbot.de", "mailde.de", "mailde.info",
    "muellmail.com", "byom.de", "kurzepost.de", "objectmail.com",
    "proxymail.eu", "rcpt.at", "trash-me.com", "0815.ru", "0wnd.net",
    "1secmail.com", "1secmail.net", "1secmail.org", "esiix.com", "wwjmp.com",
    "xojxe.com", "yoggm.com", "lroid.com", "mail-temp.com", "mailtm.com",
    "mailto.plus", "fexpost.com", "fexbox.org", "rover.info", "vusra.com",
    "robot-mail.com", "tempmail.plus", "freeml.net", "armyspy.com",
    "cuvox.de", "dayrep.com", "einrot.com", "fleckens.hu", "gustr.com",
    "jourrapide.com", "rhyta.com", "superrito.com", "teleworm.us",
}


def _domain_of(email: str) -> str:
    match = _EMAIL_RE.match((email or "").strip().lower())
    return match.group(1) if match else ""


def is_valid_email_format(email: str) -> bool:
    return bool(_EMAIL_RE.match((email or "").strip().lower()))


def is_disposable_email(email: str) -> bool:
    return _domain_of(email) in DISPOSABLE_DOMAINS


def validate_signup_email(email: str) -> tuple[bool, str | None]:
    """Retorna (ok, mensagem_de_erro). Mensagem em pt-BR para exibir no form."""
    domain = _domain_of(email)
    if not domain:
        return False, "Informe um e-mail válido."
    if domain in DISPOSABLE_DOMAINS:
        return False, (
            "E-mails temporários ou descartáveis não são aceitos. "
            "Use um e-mail do Google, Hotmail, Outlook, iCloud ou de domínio próprio."
        )
    return True, None
