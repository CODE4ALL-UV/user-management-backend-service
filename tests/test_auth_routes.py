import pytest
from fastapi import HTTPException

from user_management_service.presentation.api.auth_routes import (
    IdTokenRequest,
    _extract_google_token,
    _parse_dev_identity,
    _token_kind,
)


def test_parse_dev_identity_accepts_local_token():
    email, name = _parse_dev_identity('dev:usuario@local.test:Juan')

    assert email == 'usuario@local.test'
    assert name == 'Juan'


def test_token_kind_detects_google_access_tokens():
    assert _token_kind('ya29.a0ExampleAccessToken') == 'access_token'
    assert _token_kind('eyJhbGciOiJSUzI1NiIsImtpZCI6InRlc3QifQ.abc.def') == 'id_token'


def test_extract_google_token_prefers_access_token_when_present():
    request = IdTokenRequest(access_token='access-token-value', id_token='id-token-value')

    assert _extract_google_token(request) == 'access-token-value'


def test_dev_token_is_rejected_unless_enabled(monkeypatch):
    # Con un token dev: cualquiera podía entrar con la cuenta de la dirección.
    from user_management_service.presentation.api.auth_routes import google_sign_in

    monkeypatch.delenv('ALLOW_DEV_LOGIN', raising=False)

    with pytest.raises(HTTPException) as error:
        google_sign_in(IdTokenRequest(id_token='dev:director@univalle.edu.co'), db=None)

    assert error.value.status_code == 401


def test_staff_roles_need_their_invitation_code(monkeypatch):
    # Antes el rol del formulario se aceptaba tal cual: cualquiera se daba de
    # alta como director.
    from user_management_service.presentation.api.auth_routes import _check_staff_invitation

    monkeypatch.setenv('DOCENTE_SIGNUP_CODE', 'clave-docente')
    monkeypatch.delenv('DIRECTOR_SIGNUP_CODE', raising=False)

    # Estudiante no necesita código.
    _check_staff_invitation(None, None)
    _check_staff_invitation('estudiante', None)
    # Docente con su código, sin importar mayúsculas en el rol.
    _check_staff_invitation('Docente', ' clave-docente ')

    rejected = [
        ('docente', None),
        ('docente', 'otra-clave'),
        # El código de docente no abre la puerta de director.
        ('director', 'clave-docente'),
        # Sin código configurado, el registro de director queda cerrado.
        ('director', ''),
    ]
    for rol, code in rejected:
        with pytest.raises(HTTPException) as error:
            _check_staff_invitation(rol, code)
        assert error.value.status_code == 403, (rol, code)


def test_google_session_carries_the_role(monkeypatch):
    # Sin el rol en el token, un docente que entraba con Google recibía 403
    # al editar el curso.
    from types import SimpleNamespace

    import user_management_service.presentation.api.auth_routes as auth_routes
    from user_management_service.core.security import decode_access_token

    class FakeRepo:
        def __init__(self, db):
            pass

        def get_user_by_email(self, email):
            return SimpleNamespace(
                id_usuario=5, correo=email, nombre='Laura', rol='docente', foto_path=None
            )

    monkeypatch.setenv('ALLOW_DEV_LOGIN', '1')
    monkeypatch.setattr(auth_routes, 'UserRepositoryImpl', FakeRepo)

    result = auth_routes.google_sign_in(
        IdTokenRequest(id_token='dev:laura@univalle.edu.co'), db=None
    )

    claims = decode_access_token(result['access_token'])
    assert claims['rol'] == 'docente'
    assert claims['sub'] == '5'
