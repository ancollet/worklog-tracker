from __future__ import annotations

import io
import json
import urllib.error
import urllib.parse

import pytest

from worklog.services import salesforce as sf


class _FakeResponse:
    def __init__(self, payload, status: int = 200) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(code: int, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else b""
    return urllib.error.HTTPError(
        url="https://x", code=code, msg="err", hdrs=None, fp=io.BytesIO(body),
    )


class _FakeTransport:
    """Scripted stand-in for urlopen: records every request, replays queued answers."""

    def __init__(self, *answers) -> None:
        self.answers = list(answers)
        self.requests = []

    def __call__(self, req, timeout=15):
        self.requests.append(req)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def token_requests(self):
        return [r for r in self.requests if r.full_url.endswith("/services/oauth2/token")]


def _token(value: str = "tok-1"):
    return _FakeResponse({"access_token": value, "token_type": "Bearer",
                          "instance_url": "https://acme.my.salesforce.com"})


def _creds():
    return sf.SalesforceCredentials(
        instance_url="https://acme.my.salesforce.com/",  # trailing slash should be normalized
        consumer_key="key-123",
        consumer_secret="s3cret",
    )


def _headers(req) -> dict:
    return {k.lower(): v for k, v in req.header_items()}


def test_test_connection_fetches_token_with_client_credentials():
    transport = _FakeTransport(_token("tok-1"), _FakeResponse({"sobjects": "/x"}))

    sf.SalesforceClient(_creds(), opener=transport).test_connection()

    token_req, api_req = transport.requests
    assert token_req.full_url == "https://acme.my.salesforce.com/services/oauth2/token"
    assert token_req.get_method() == "POST"
    form = urllib.parse.parse_qs(token_req.data.decode("utf-8"))
    assert form == {
        "grant_type": ["client_credentials"],
        "client_id": ["key-123"],
        "client_secret": ["s3cret"],
    }
    assert _headers(token_req)["content-type"] == "application/x-www-form-urlencoded"
    assert api_req.full_url.startswith("https://acme.my.salesforce.com/services/data/v")
    assert _headers(api_req)["authorization"] == "Bearer tok-1"


_SESSION_EXPIRED = [{"message": "Session expired or invalid", "errorCode": "INVALID_SESSION_ID"}]


def test_token_is_kept_in_memory_and_reused():
    transport = _FakeTransport(_token(), _FakeResponse({}), _FakeResponse({}))
    client = sf.SalesforceClient(_creds(), opener=transport)

    client.test_connection()
    client.test_connection()

    assert len(transport.token_requests()) == 1


def test_401_renews_token_once_and_repeats_the_call():
    transport = _FakeTransport(
        _token("old"), _http_error(401, _SESSION_EXPIRED),
        _token("new"), _FakeResponse({}),
    )

    sf.SalesforceClient(_creds(), opener=transport).test_connection()

    assert len(transport.token_requests()) == 2
    first_call, second_call = transport.requests[1], transport.requests[3]
    assert first_call.full_url == second_call.full_url
    assert _headers(first_call)["authorization"] == "Bearer old"
    assert _headers(second_call)["authorization"] == "Bearer new"


def test_second_401_gives_up_without_a_further_retry():
    transport = _FakeTransport(
        _token("old"), _http_error(401, _SESSION_EXPIRED),
        _token("new"), _http_error(401, _SESSION_EXPIRED),
    )

    with pytest.raises(sf.SalesforceAuthError):
        sf.SalesforceClient(_creds(), opener=transport).test_connection()

    assert len(transport.requests) == 4
    assert transport.answers == []


def test_rejected_sign_in_raises_auth_error_with_salesforce_text():
    transport = _FakeTransport(_http_error(400, {
        "error": "invalid_client", "error_description": "invalid client credentials",
    }))

    with pytest.raises(sf.SalesforceAuthError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).test_connection()

    assert "invalid client credentials" in str(excinfo.value)
    assert "s3cret" not in str(excinfo.value)
    assert len(transport.requests) == 1  # no API call without a token


def test_server_error_during_sign_in_is_not_reported_as_rejected_sign_in():
    transport = _FakeTransport(_http_error(503))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).test_connection()

    assert "503" in str(excinfo.value)


def test_network_error_during_sign_in_raises_network_error():
    transport = _FakeTransport(urllib.error.URLError("Name or service not known"))

    with pytest.raises(sf.SalesforceNetworkError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).test_connection()

    assert "Name or service not known" in str(excinfo.value)
    assert not isinstance(excinfo.value, sf.SalesforceAuthError)


def test_network_error_during_call_raises_network_error():
    transport = _FakeTransport(_token(), TimeoutError("timed out"))

    with pytest.raises(sf.SalesforceNetworkError):
        sf.SalesforceClient(_creds(), opener=transport).test_connection()


def test_org_error_carries_the_message_text_from_salesforce():
    transport = _FakeTransport(_token(), _http_error(403, [
        {"message": "The REST API is not enabled for this Organization.",
         "errorCode": "API_DISABLED_FOR_ORG"},
    ]))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).test_connection()

    assert "The REST API is not enabled for this Organization." in str(excinfo.value)
    assert not isinstance(excinfo.value, (sf.SalesforceAuthError, sf.SalesforceNetworkError))
    assert len(transport.token_requests()) == 1  # only a 401 renews the token


def test_org_error_joins_several_messages():
    transport = _FakeTransport(_token(), _http_error(400, [
        {"message": "Erste Meldung", "errorCode": "A"},
        {"message": "Zweite Meldung", "errorCode": "B"},
    ]))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).test_connection()

    assert "Erste Meldung" in str(excinfo.value)
    assert "Zweite Meldung" in str(excinfo.value)


def test_org_error_without_readable_body_still_names_the_status():
    transport = _FakeTransport(_token(), _http_error(500))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).test_connection()

    assert "500" in str(excinfo.value)


def test_token_answer_without_access_token_is_a_readable_error():
    transport = _FakeTransport(_FakeResponse({"unexpected": True}))

    with pytest.raises(sf.SalesforceError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).test_connection()

    assert "Zugriffstoken" in str(excinfo.value)


def test_instance_url_without_scheme_is_a_readable_error_without_network():
    transport = _FakeTransport()
    creds = sf.SalesforceCredentials("acme.my.salesforce.com", "key", "secret")

    with pytest.raises(sf.SalesforceError) as excinfo:
        sf.SalesforceClient(creds, opener=transport).test_connection()

    assert "Instance-URL" in str(excinfo.value)
    assert transport.requests == []
