"""Credential-bearing URLs and JWTs stay private without eating diagnostics."""

import base64
import json
import os

import pytest

from core import redact
from core.redact import scrub_secrets


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    for name in list(os.environ):
        if (name.upper().endswith(redact.SECRET_ENV_SUFFIXES)
                or name.upper() in {"KEY", "TOKEN", "SECRET", "PASSWORD"}):
            monkeypatch.delenv(name, raising=False)


def jwt(header=None, claims=None):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")
    return ".".join((encode(header if header is not None else {"alg": "HS256", "typ": "JWT"}),
                     encode(claims if claims is not None else {"sub": "dummy-only", "exp": 1234567890}),
                     "dummy_signature_not_a_real_credential"))


@pytest.mark.parametrize("name", [
    "token", "password", "api_key", "api-key", "apikey", "key", "access_token",
    "refresh_token", "id_token", "passwd", "secret", "client_secret",
    "authorization", "auth_token", "X-Amz-Signature", "X-Amz-Security-Token",
    "MYAPP_TOKEN", "%74oken", "api%5Fkey", "access%2Dtoken",
])
@pytest.mark.parametrize("position", ["?", "?page=2&"])
def test_query_secret_is_removed_without_changing_adjacent_url_bytes(name, position):
    original = f"https://example.org/home/report{position}{name}=dummy%2Bsecret%3D123&lang=zh-Hant#section-2"
    expected = f"https://example.org/home/report{position}{name}=<redacted:query-credential>&lang=zh-Hant#section-2"
    assert scrub_secrets(original) == expected
    assert scrub_secrets(expected) == expected


def test_repeated_query_credentials_and_surrounding_prose_survive():
    original = 'Failed URL "https://example.org/x?token=one&token=two&password=x"; status=401'
    expected = ('Failed URL "https://example.org/x?token=<redacted:query-credential>'
                '&token=<redacted:query-credential>&password=<redacted:query-credential>"; status=401')
    assert scrub_secrets(original) == expected


@pytest.mark.parametrize("text", [
    "https://example.org/token/password/api_key?limit=20&offset=40#tokens",
    "https://example.org/x?token_count=450&password_policy=strict&key_count=3",
    "https://example.org/x?token=&q=retained",
    "https://example.org/x?next=%2Fhome%2Freport&q=causal%20influence",
    "A token is an input unit; the password policy requires a long password.",
    "package.version.number builds normally; 1.2.34567890 is a version.",
    "/home/analyst/report.md is an operator path kept by scrub_secrets.",
    "https://example.org/data?rows=50&fields=title,date&labels=a%2Cb",
])
def test_nonsecret_data_and_url_content_are_byte_identical(text):
    assert scrub_secrets(text) == text


@pytest.mark.parametrize("prefix,suffix", [
    ("", ""), ('stored "', '" here'), ("failure (", ") after 401"),
    ("https://example.org/result?opaque=", "&count=20#source"),
])
def test_standalone_well_shaped_jwt_is_removed(prefix, suffix):
    token = jwt()
    result = scrub_secrets(prefix + token + suffix)
    assert result == prefix + "<redacted:jwt>" + suffix
    assert scrub_secrets(result) == result


@pytest.mark.parametrize("header,claims", [
    ({"typ": "JWT"}, {"sub": "dummy"}),
    ({"alg": 1}, {"sub": "dummy"}),
    ([], {"sub": "dummy"}),
    ({"alg": "HS256"}, ["ordinary", "data"]),
])
def test_dotted_non_jwt_json_is_not_treated_as_a_credential(header, claims):
    text = jwt(header, claims)
    assert scrub_secrets(text) == text


def test_exact_environment_secret_is_removed_before_shape_rules(monkeypatch):
    token = jwt()
    monkeypatch.setenv("TEST_ACCESS_TOKEN", token)
    original = "https://example.org/x?access_token=" + token + "&count=2"
    expected = "https://example.org/x?access_token=<redacted:TEST_ACCESS_TOKEN>&count=2"
    assert scrub_secrets(original) == expected
    assert scrub_secrets(expected) == expected
    assert scrub_secrets("Bearer " + token) == "Bearer <redacted:TEST_ACCESS_TOKEN>"


@pytest.mark.parametrize("length", [1, 8, 30, 100, 500])
def test_redact_before_bounding_never_leaves_a_credential_prefix(length):
    token = jwt()
    query_secret = "dummy-query-secret-long-enough-to-recognize"
    original = "https://example.org/x?token=" + query_secret + "&next=" + token
    bounded = scrub_secrets(original)[:length]
    assert "dummy-query" not in bounded
    assert token[:12] not in bounded


def test_credential_pass_keeps_its_linear_long_text_behavior():
    # A malformed candidate must not start a new scan at every character.
    text = "a" * 200_000 + "." + "b" * 200_000
    assert scrub_secrets(text) == text
