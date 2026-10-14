"""El enlace para cambiar la contraseña.

No se guarda en la base de datos, así que todo lo que lo hace seguro va
dentro del propio enlace: caduca, sirve una vez y no vale como sesión.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest

from user_management_service.application.use_cases import password_reset
from user_management_service.core import mailer
from user_management_service.core.security import (
    ALGORITHM,
    decode_access_token,
    get_password_hash,
    verify_password,
)


class FakeRepo:
    def __init__(self):
        self.user = SimpleNamespace(
            id_usuario=3,
            correo="Ana@Example.com",
            nombre="Ana",
            password=get_password_hash("clave-vieja"),
        )

    def find_by_email_any_case(self, email):
        return self.user if email.lower() == self.user.correo.lower() else None

    def get_user_by_id(self, user_id):
        return self.user if user_id == self.user.id_usuario else None

    def update_password(self, user_id, password_hash):
        self.user.password = password_hash


@pytest.fixture
def sent(monkeypatch):
    mails = []
    monkeypatch.setattr(mailer, "send_mail", lambda **mail: mails.append(mail))
    # Un registro de envíos vacío solo para esta prueba.
    monkeypatch.setattr(password_reset, "_last_sent", {})
    return mails


def _token_from(mail):
    link = mail["text"].split("abre este enlace:\n\n", 1)[1].split("\n", 1)[0]
    return parse_qs(urlparse(link).query)["restablecer"][0]


def test_the_link_changes_the_password_once(sent):
    repo = FakeRepo()

    password_reset.request_reset(repo, "ana@example.com", "https://code4all-web.onrender.com")
    token = _token_from(sent[0])
    password_reset.reset_password(repo, token, "clave-nueva")

    assert verify_password("clave-nueva", repo.user.password)
    with pytest.raises(password_reset.InvalidResetLink):
        password_reset.reset_password(repo, token, "otra-clave")


def test_the_mail_goes_to_the_account_and_points_to_the_web(sent):
    repo = FakeRepo()

    password_reset.request_reset(repo, "ANA@example.com", "https://code4all-web.onrender.com/")

    assert len(sent) == 1
    assert sent[0]["to_email"] == "Ana@Example.com"
    assert "https://code4all-web.onrender.com/?restablecer=" in sent[0]["text"]
    assert "30 minutos" in sent[0]["text"]


def test_an_unknown_address_gets_no_mail(sent):
    password_reset.request_reset(FakeRepo(), "nadie@example.com", "https://x")

    assert sent == []


def test_asking_again_right_away_does_not_send_another(sent):
    repo = FakeRepo()

    password_reset.request_reset(repo, "ana@example.com", "https://x")
    password_reset.request_reset(repo, "ana@example.com", "https://x")

    assert len(sent) == 1


def test_an_expired_link_does_not_work():
    repo = FakeRepo()
    old = datetime.now(timezone.utc) - timedelta(minutes=password_reset.LINK_MINUTES + 1)
    token = password_reset.create_reset_token(repo.user, now=old)

    with pytest.raises(password_reset.InvalidResetLink):
        password_reset.reset_password(repo, token, "clave-nueva")


def test_a_link_stops_working_if_the_password_changed_meanwhile():
    repo = FakeRepo()
    token = password_reset.create_reset_token(repo.user)
    repo.user.password = get_password_hash("cambiada-por-otro-lado")

    with pytest.raises(password_reset.InvalidResetLink):
        password_reset.reset_password(repo, token, "clave-nueva")


def test_the_link_is_not_a_session():
    # Los demás servicios aceptan cualquier token firmado con SECRET_KEY: si
    # el enlace se firmara igual, quien lo tuviera entraría sin contraseña.
    token = password_reset.create_reset_token(FakeRepo().user)

    with pytest.raises(ValueError):
        decode_access_token(token)


def test_a_session_is_not_a_link():
    from user_management_service.core.security import create_access_token

    session = create_access_token({"sub": "3", "email": "Ana@Example.com", "rol": "estudiante"})

    with pytest.raises(password_reset.InvalidResetLink):
        password_reset.reset_password(FakeRepo(), session, "clave-nueva")


def test_the_new_password_follows_the_same_rules_as_signing_up():
    repo = FakeRepo()
    token = password_reset.create_reset_token(repo.user)

    with pytest.raises(ValueError, match="6"):
        password_reset.reset_password(repo, token, "corta")
    with pytest.raises(ValueError, match="72"):
        password_reset.reset_password(repo, token, "x" * 73)

    assert verify_password("clave-vieja", repo.user.password)


def test_if_the_mail_fails_one_can_ask_again(monkeypatch):
    sent = []

    def flaky(**mail):
        if not sent:
            sent.append("fallo")
            raise RuntimeError("Brevo no responde")
        sent.append(mail)

    monkeypatch.setattr(mailer, "send_mail", flaky)
    monkeypatch.setattr(password_reset, "_last_sent", {})
    repo = FakeRepo()

    password_reset.request_reset(repo, "ana@example.com", "https://x")
    password_reset.request_reset(repo, "ana@example.com", "https://x")

    assert len(sent) == 2


def test_mail_is_configured_only_with_brevo_or_locally(monkeypatch):
    for name in ("BREVO_API_KEY", "MAIL_FROM", "ALLOW_DEV_LOGIN"):
        monkeypatch.delenv(name, raising=False)
    assert not mailer.mail_configured()

    monkeypatch.setenv("BREVO_API_KEY", "clave")
    assert not mailer.mail_configured()  # falta el remitente

    monkeypatch.setenv("MAIL_FROM", "code4all@example.com")
    assert mailer.mail_configured()


def test_brevo_receives_the_mail(monkeypatch):
    calls = []

    class Ok:
        def raise_for_status(self):
            pass

    monkeypatch.setenv("BREVO_API_KEY", "clave-brevo")
    monkeypatch.setenv("MAIL_FROM", "code4all@example.com")
    monkeypatch.delenv("MAIL_FROM_NAME", raising=False)
    monkeypatch.setattr(
        mailer.requests, "post", lambda url, **kwargs: calls.append((url, kwargs)) or Ok()
    )

    mailer.send_mail(to_email="ana@example.com", to_name="Ana", subject="Hola", text="t", html="<p>t</p>")

    url, kwargs = calls[0]
    assert url == mailer.BREVO_URL
    assert kwargs["headers"]["api-key"] == "clave-brevo"
    assert kwargs["json"]["sender"] == {"name": "Code4All", "email": "code4all@example.com"}
    assert kwargs["json"]["to"] == [{"email": "ana@example.com", "name": "Ana"}]


def _signed_link(claims):
    """Un enlace firmado con la clave de los enlaces, con lo que se quiera dentro."""
    claims = {"exp": datetime.now(timezone.utc) + timedelta(minutes=5), **claims}
    return jwt.encode(claims, password_reset._signing_key(), algorithm=ALGORITHM)


def test_a_link_signed_for_another_purpose_does_not_work():
    repo = FakeRepo()
    token = _signed_link(
        {"sub": "3", "purpose": "otra-cosa", "pwd": password_reset._fingerprint(repo.user.password)}
    )

    with pytest.raises(password_reset.InvalidResetLink):
        password_reset.reset_password(repo, token, "clave-nueva")

    assert verify_password("clave-vieja", repo.user.password)


@pytest.mark.parametrize("claims", [{"sub": "no-es-un-numero"}, {}])
def test_a_link_without_a_valid_user_id_does_not_work(claims):
    repo = FakeRepo()
    token = _signed_link(
        {"purpose": password_reset.PURPOSE, "pwd": password_reset._fingerprint(repo.user.password), **claims}
    )

    with pytest.raises(password_reset.InvalidResetLink):
        password_reset.reset_password(repo, token, "clave-nueva")


def test_a_link_for_an_account_that_no_longer_exists_does_not_work():
    repo = FakeRepo()
    token = password_reset.create_reset_token(repo.user)
    repo.user.id_usuario = 99  # la cuenta 3 ya no está

    with pytest.raises(password_reset.InvalidResetLink):
        password_reset.reset_password(repo, token, "clave-nueva")


def test_the_name_in_the_mail_cannot_inject_html(sent):
    repo = FakeRepo()
    repo.user.nombre = '<img src=x onerror="alert(1)">'

    password_reset.request_reset(repo, "ana@example.com", "https://x")

    assert "<img" not in sent[0]["html"]
    assert "&lt;img" in sent[0]["html"]
    # El texto plano va tal cual: no lo interpreta ningún navegador.
    assert repo.user.nombre in sent[0]["text"]


def test_locally_without_brevo_the_mail_is_printed(monkeypatch, capsys):
    monkeypatch.delenv("BREVO_API_KEY", raising=False)
    monkeypatch.delenv("MAIL_FROM", raising=False)
    monkeypatch.setenv("ALLOW_DEV_LOGIN", "yes")

    def no_network(*args, **kwargs):
        raise AssertionError("no debería llamar a Brevo")

    monkeypatch.setattr(mailer.requests, "post", no_network)

    assert mailer.mail_configured()
    mailer.send_mail(
        to_email="ana@example.com", to_name="Ana", subject="Asunto", text="El enlace", html="<p>x</p>"
    )

    out = capsys.readouterr().out
    assert "Correo para ana@example.com" in out
    assert "Asunto" in out
    assert "El enlace" in out


def test_without_brevo_and_outside_local_the_mail_fails(monkeypatch):
    monkeypatch.setenv("BREVO_API_KEY", "clave")
    monkeypatch.delenv("MAIL_FROM", raising=False)
    monkeypatch.delenv("ALLOW_DEV_LOGIN", raising=False)

    with pytest.raises(mailer.MailNotConfigured):
        mailer.send_mail(to_email="ana@example.com", to_name="Ana", subject="s", text="t", html="h")


def test_brevo_uses_the_configured_sender_name_and_the_email_as_fallback_name(monkeypatch):
    calls = []

    class Ok:
        def raise_for_status(self):
            pass

    monkeypatch.setenv("BREVO_API_KEY", "clave-brevo")
    monkeypatch.setenv("MAIL_FROM", " code4all@example.com ")
    monkeypatch.setenv("MAIL_FROM_NAME", "Curso Code4All")
    monkeypatch.setattr(mailer.requests, "post", lambda url, **kwargs: calls.append(kwargs) or Ok())

    mailer.send_mail(to_email="ana@example.com", to_name="", subject="s", text="t", html="h")

    sent_json = calls[0]["json"]
    assert sent_json["sender"] == {"name": "Curso Code4All", "email": "code4all@example.com"}
    assert sent_json["to"] == [{"email": "ana@example.com", "name": "ana@example.com"}]
    assert calls[0]["timeout"] == 10


def test_if_brevo_refuses_the_mail_the_error_is_raised(monkeypatch):
    class Refused:
        def raise_for_status(self):
            raise mailer.requests.HTTPError("401 Unauthorized")

    monkeypatch.setenv("BREVO_API_KEY", "clave-mala")
    monkeypatch.setenv("MAIL_FROM", "code4all@example.com")
    monkeypatch.setattr(mailer.requests, "post", lambda url, **kwargs: Refused())

    with pytest.raises(mailer.requests.HTTPError):
        mailer.send_mail(to_email="ana@example.com", to_name="Ana", subject="s", text="t", html="h")
