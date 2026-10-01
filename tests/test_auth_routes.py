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

