"""Envío de correos: por ahora, solo el de recuperar la contraseña.

Va por la API HTTP de Brevo y no por SMTP porque Render, en el plan gratuito,
bloquea desde septiembre de 2025 los puertos 25, 465 y 587: un servidor SMTP
no llegaría a conectar nunca. Brevo no pide dominio propio; basta con
verificar en su panel el correo que se pone en MAIL_FROM.

Variables:
    BREVO_API_KEY   la clave de la API (Brevo → SMTP & API → API Keys).
    MAIL_FROM       el remitente, ya verificado en Brevo.
    MAIL_FROM_NAME  el nombre que ve quien lo recibe. Por defecto, Code4All.

En local, sin Brevo, con ALLOW_DEV_LOGIN=1 el correo no se envía: se escribe
en la consola del servidor para poder copiar el enlace.
"""

import logging
import os

import requests

logger = logging.getLogger(__name__)

BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class MailNotConfigured(RuntimeError):
    """No hay con qué enviar correos."""


def _dev_mode() -> bool:
    return os.getenv("ALLOW_DEV_LOGIN", "").strip().lower() in {"1", "true", "yes"}


def mail_configured() -> bool:
    has_brevo = bool(os.getenv("BREVO_API_KEY", "").strip()) and bool(
        os.getenv("MAIL_FROM", "").strip()
    )
    return has_brevo or _dev_mode()


def send_mail(*, to_email: str, to_name: str, subject: str, text: str, html: str) -> None:
    """Envía un correo. Lanza una excepción si no sale."""
    api_key = os.getenv("BREVO_API_KEY", "").strip()
    sender = os.getenv("MAIL_FROM", "").strip()

    if not api_key or not sender:
        if _dev_mode():
            print(f"\n--- Correo para {to_email} ---\n{subject}\n\n{text}\n---\n", flush=True)
            return
        raise MailNotConfigured("Faltan BREVO_API_KEY o MAIL_FROM")

    response = requests.post(
        BREVO_URL,
        headers={
            "api-key": api_key,
            "accept": "application/json",
            "content-type": "application/json",
        },
        json={
            "sender": {
                "name": os.getenv("MAIL_FROM_NAME", "").strip() or "Code4All",
                "email": sender,
            },
            "to": [{"email": to_email, "name": to_name or to_email}],
            "subject": subject,
            "textContent": text,
            "htmlContent": html,
        },
        timeout=10,
    )
    response.raise_for_status()
