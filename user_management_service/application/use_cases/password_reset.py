"""Recuperar la contraseña con un enlace que llega al correo.

El enlace lleva un token firmado por el servidor. No hace falta guardar nada
en la base de datos:

- Caduca a los 30 minutos (`exp`).
- Vale una sola vez: lleva una huella de la contraseña actual. Al cambiarla,
  bcrypt genera un hash nuevo, la huella deja de coincidir y el enlace ya no
  sirve. Tampoco sirve si la contraseña cambió por otro camino entretanto.
- Se firma con una clave derivada de SECRET_KEY y no con SECRET_KEY a secas,
  para que no pueda usarse como sesión en el resto de servicios, que aceptan
  cualquier token firmado con SECRET_KEY.
"""

import hashlib
import html
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import jwt

from user_management_service.core import mailer
from user_management_service.core.security import ALGORITHM, SECRET_KEY, get_password_hash

PURPOSE = "password_reset"
LINK_MINUTES = 30
MIN_PASSWORD = 6
# bcrypt solo mira los primeros 72 bytes: más allá, dos contraseñas
# distintas serían la misma sin que nadie lo supiera.
MAX_PASSWORD_BYTES = 72

# Para que nadie llene el buzón de otra persona pidiendo enlaces sin parar,
# ni gaste el cupo diario de correos: uno por dirección cada minuto. Vive en
# memoria porque el gateway corre en un solo proceso.
COOLDOWN_SECONDS = 60
_last_sent: dict[str, float] = {}


class InvalidResetLink(ValueError):
    """El enlace no sirve: caducó, ya se usó o no es nuestro."""


def _signing_key() -> str:
    return f"{SECRET_KEY}:{PURPOSE}"


def _fingerprint(password_hash: str) -> str:
    return hashlib.sha256((password_hash or "").encode()).hexdigest()[:24]


def create_reset_token(user, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user.id_usuario),
            "purpose": PURPOSE,
            "pwd": _fingerprint(user.password),
            "exp": now + timedelta(minutes=LINK_MINUTES),
        },
        _signing_key(),
        algorithm=ALGORITHM,
    )


def check_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise ValueError(f"La contraseña debe tener al menos {MIN_PASSWORD} caracteres.")
    if len(password.encode()) > MAX_PASSWORD_BYTES:
        raise ValueError("La contraseña es demasiado larga: usa como máximo 72 caracteres.")


def reset_link(token: str, frontend_url: str) -> str:
    return f"{frontend_url.rstrip('/')}/?restablecer={quote(token)}"


def request_reset(repo, email: str, frontend_url: str) -> None:
    """Envía el enlace si hay una cuenta con ese correo.

    No dice si la había: quien escriba correos al azar no debe poder saber
    quién está registrado. Por eso tampoco se avisa si el envío falla; queda
    en el registro del servidor.
    """
    user = repo.find_by_email_any_case(email)
    if user is None:
        return

    key = user.correo.lower()
    now = time.monotonic()
    if now - _last_sent.get(key, -COOLDOWN_SECONDS) < COOLDOWN_SECONDS:
        return
    _last_sent[key] = now

    link = reset_link(create_reset_token(user), frontend_url)
    name = user.nombre or ""
    text = (
        f"Hola {name}:\n\n"
        "Alguien pidió cambiar la contraseña de tu cuenta de Code4All. "
        "Para elegir una nueva, abre este enlace:\n\n"
        f"{link}\n\n"
        f"El enlace sirve una sola vez y caduca en {LINK_MINUTES} minutos.\n\n"
        "Si no fuiste tú, no hagas nada: tu contraseña sigue siendo la misma."
    )
    safe_name = html.escape(name)
    safe_link = html.escape(link, quote=True)
    body = (
        '<div style="font-family:Arial,sans-serif;font-size:18px;line-height:1.5;color:#1a1a1a">'
        f"<p>Hola {safe_name}:</p>"
        "<p>Alguien pidió cambiar la contraseña de tu cuenta de Code4All.</p>"
        f'<p><a href="{safe_link}" style="display:inline-block;padding:14px 22px;'
        'background:#1565C0;color:#ffffff;border-radius:8px;text-decoration:none;'
        'font-weight:bold">Elegir una contraseña nueva</a></p>'
        f"<p>El enlace sirve una sola vez y caduca en {LINK_MINUTES} minutos.</p>"
        "<p>Si el botón no funciona, copia esta dirección en el navegador:<br>"
        f'<span style="word-break:break-all">{safe_link}</span></p>'
        "<p>Si no fuiste tú, no hagas nada: tu contraseña sigue siendo la misma.</p>"
        "</div>"
    )

    try:
        mailer.send_mail(
            to_email=user.correo,
            to_name=name,
            subject="Cambia tu contraseña de Code4All",
            text=text,
            html=body,
        )
    except Exception:
        # Que pueda pedirlo otra vez enseguida si fue un fallo pasajero.
        _last_sent.pop(key, None)
        mailer.logger.exception("No se pudo enviar el correo de recuperación")


def reset_password(repo, token: str, new_password: str) -> None:
    check_new_password(new_password)

    try:
        payload = jwt.decode(token, _signing_key(), algorithms=[ALGORITHM])
    except jwt.PyJWTError as error:
        raise InvalidResetLink() from error

    if payload.get("purpose") != PURPOSE:
        raise InvalidResetLink()

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError) as error:
        raise InvalidResetLink() from error

    user = repo.get_user_by_id(user_id)
    if user is None or payload.get("pwd") != _fingerprint(user.password):
        raise InvalidResetLink()

    repo.update_password(user_id, get_password_hash(new_password))
