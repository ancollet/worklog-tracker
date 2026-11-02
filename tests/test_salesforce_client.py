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


_OPEN_STATUSES = ", ".join(f"'{status}'" for status in sf.PROJECT_OPEN_STATUSES)

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


# ---- User suchen (leistende Person), inaktive eingeschlossen ----

def _query_result(*records):
    return _FakeResponse({"totalSize": len(records), "done": True, "records": [
        {"attributes": {"type": "User", "url": "/x"}, **r} for r in records
    ]})


def _soql(req) -> str:
    parsed = urllib.parse.urlsplit(req.full_url)
    assert parsed.path == f"/services/data/{sf.API_VERSION}/query"
    return urllib.parse.parse_qs(parsed.query, strict_parsing=True)["q"][0]


def test_search_users_returns_id_name_and_email():
    transport = _FakeTransport(_token(), _query_result(
        {"Id": "005AA0000012345IAA", "Name": "Anna Collet", "Email": "anna@example.com"},
        {"Id": "005AA0000067890IAA", "Name": "Annabel Roth", "Email": None},
    ))

    users = sf.SalesforceClient(_creds(), opener=transport).search_users("anna")

    assert users == [
        sf.SalesforceUser(id="005AA0000012345IAA", name="Anna Collet", email="anna@example.com"),
        sf.SalesforceUser(id="005AA0000067890IAA", name="Annabel Roth", email=""),
    ]
    assert transport.requests[1].get_method() == "GET"


def test_search_asks_for_users_matching_name_or_email_with_a_limit():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).search_users("  anna ", limit=7)

    soql = _soql(transport.requests[1])
    assert "FROM User" in soql
    assert "IsActive" not in soql  # inactive users are candidates too
    assert "Name LIKE '%anna%'" in soql
    assert "Email LIKE '%anna%'" in soql
    assert soql.endswith("ORDER BY Name LIMIT 7")


def test_apostrophe_in_search_text_cannot_break_out_of_the_string():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).search_users("O'Brien")

    soql = _soql(transport.requests[1])
    assert r"Name LIKE '%O\'Brien%'" in soql
    assert r"Email LIKE '%O\'Brien%'" in soql


def test_injection_attempt_stays_inside_the_string_literal():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).search_users(
        "x%' OR IsActive = false OR Name LIKE '"
    )

    soql = _soql(transport.requests[1])
    # every apostrophe of the input is escaped, so only our own four quotes delimit literals
    assert soql.replace(r"\'", "").count("'") == 4


def test_backslash_is_escaped_before_the_apostrophe():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).search_users("a\\' OR Id != '")

    soql = _soql(transport.requests[1])
    # input \' must become \\ + \' — not \\' which would close the literal
    assert r"Name LIKE '%a\\\' OR Id != \'%'" in soql


def test_like_wildcards_in_search_text_are_taken_literally():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).search_users("a_b%c")

    assert r"Name LIKE '%a\_b\%c%'" in _soql(transport.requests[1])


def test_line_breaks_and_double_quotes_in_search_text_are_escaped():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).search_users('a\n"b\r\tc')

    soql = _soql(transport.requests[1])
    assert "\n" not in soql and "\r" not in soql and "\t" not in soql
    assert r'\"' in soql


def test_blank_search_text_returns_nothing_without_asking_salesforce():
    transport = _FakeTransport()

    assert sf.SalesforceClient(_creds(), opener=transport).search_users("   ") == []
    assert transport.requests == []


def test_limit_is_kept_within_sane_bounds():
    transport = _FakeTransport(_token(), _query_result(), _query_result())
    client = sf.SalesforceClient(_creds(), opener=transport)

    client.search_users("a", limit=0)
    client.search_users("a", limit=100000)

    assert _soql(transport.requests[1]).endswith("LIMIT 1")
    assert _soql(transport.requests[2]).endswith("LIMIT 200")


def test_search_without_hits_returns_an_empty_list():
    transport = _FakeTransport(_token(), _query_result())

    assert sf.SalesforceClient(_creds(), opener=transport).search_users("niemand") == []


def test_network_error_during_search_raises_network_error():
    transport = _FakeTransport(_token(), urllib.error.URLError("Network is unreachable"))

    with pytest.raises(sf.SalesforceNetworkError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).search_users("anna")

    assert "Network is unreachable" in str(excinfo.value)


def test_org_error_during_search_carries_the_salesforce_text():
    transport = _FakeTransport(_token(), _http_error(400, [
        {"message": "sObject type 'User' is not supported.", "errorCode": "INVALID_TYPE"},
    ]))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).search_users("anna")

    assert "is not supported" in str(excinfo.value)


def test_unexpected_query_answer_is_a_readable_error():
    transport = _FakeTransport(_token(), _FakeResponse({"something": "else"}))

    with pytest.raises(sf.SalesforceError):
        sf.SalesforceClient(_creds(), opener=transport).search_users("anna")


# ---------- Accounts mit offenen Projekten (Registrieren) ----------


def test_accounts_with_open_projects_returns_id_and_name():
    transport = _FakeTransport(_token(), _query_result(
        {"Id": "001AA000001AAAAIA2", "Name": "Acme GmbH"},
        {"Id": "001AA000001BBBBIA2", "Name": "Beta AG"},
    ))

    accounts = sf.SalesforceClient(_creds(), opener=transport).list_accounts_with_open_projects()

    assert accounts == [
        sf.SalesforceAccount(id="001AA000001AAAAIA2", name="Acme GmbH"),
        sf.SalesforceAccount(id="001AA000001BBBBIA2", name="Beta AG"),
    ]


def test_accounts_query_asks_only_for_accounts_with_an_open_project():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).list_accounts_with_open_projects()

    soql = _soql(transport.requests[1])
    assert soql.startswith("SELECT Id, Name FROM Account WHERE Id IN (SELECT ")
    # the org names are assumptions kept in one place; the query must be built from them
    assert f"SELECT {sf.PROJECT_ACCOUNT_FIELD} FROM {sf.PROJECT_OBJECT} " in soql
    assert f"WHERE {sf.PROJECT_STATUS_FIELD} IN ('{sf.PROJECT_OPEN_STATUSES[0]}'" in soql
    assert soql.endswith("ORDER BY Name")


def test_no_account_with_open_projects_returns_an_empty_list():
    transport = _FakeTransport(_token(), _query_result())

    assert sf.SalesforceClient(_creds(), opener=transport).list_accounts_with_open_projects() == []


def test_accounts_beyond_the_first_batch_are_fetched_too():
    first = _FakeResponse({
        "totalSize": 2, "done": False,
        "nextRecordsUrl": f"/services/data/{sf.API_VERSION}/query/01gAA000000001-2000",
        "records": [{"Id": "001AA000001AAAAIA2", "Name": "Acme GmbH"}],
    })
    transport = _FakeTransport(_token(), first, _query_result(
        {"Id": "001AA000001BBBBIA2", "Name": "Beta AG"},
    ))

    accounts = sf.SalesforceClient(_creds(), opener=transport).list_accounts_with_open_projects()

    assert [a.name for a in accounts] == ["Acme GmbH", "Beta AG"]
    follow_up = transport.requests[2]
    assert follow_up.full_url == (
        f"https://acme.my.salesforce.com/services/data/{sf.API_VERSION}/query/01gAA000000001-2000"
    )
    assert _headers(follow_up)["authorization"] == "Bearer tok-1"


def test_network_error_while_listing_accounts_raises_network_error():
    transport = _FakeTransport(_token(), urllib.error.URLError("Network is unreachable"))

    with pytest.raises(sf.SalesforceNetworkError):
        sf.SalesforceClient(_creds(), opener=transport).list_accounts_with_open_projects()


def test_org_error_while_listing_accounts_carries_the_salesforce_text():
    transport = _FakeTransport(_token(), _http_error(400, [
        {"message": "sObject type 'Project__c' is not supported.", "errorCode": "INVALID_TYPE"},
    ]))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).list_accounts_with_open_projects()

    assert "is not supported" in str(excinfo.value)


# ---------- Offene Projekte eines Accounts (Registrieren) ----------


def test_open_projects_of_an_account_returns_id_and_name():
    transport = _FakeTransport(_token(), _query_result(
        {"Id": "a0XAA000001AAAAIA2", "Name": "Relaunch"},
        {"Id": "a0XAA000001BBBBIA2", "Name": "Wartung"},
    ))

    projects = sf.SalesforceClient(_creds(), opener=transport).list_open_projects("001AA000001AAAAIA2")

    assert projects == [
        sf.SalesforceProject(id="a0XAA000001AAAAIA2", name="Relaunch"),
        sf.SalesforceProject(id="a0XAA000001BBBBIA2", name="Wartung"),
    ]


def test_open_projects_query_asks_for_the_open_projects_of_that_account_only():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).list_open_projects(" 001AA000001AAAAIA2 ")

    # the org names are assumptions kept in one place; the query must be built from them
    assert _soql(transport.requests[1]) == (
        f"SELECT Id, {sf.PROJECT_NAME_FIELD} FROM {sf.PROJECT_OBJECT} "
        f"WHERE {sf.PROJECT_ACCOUNT_FIELD} = '001AA000001AAAAIA2' "
        f"AND {sf.PROJECT_STATUS_FIELD} IN ({_OPEN_STATUSES}) "
        f"ORDER BY {sf.PROJECT_NAME_FIELD}"
    )


def test_account_id_cannot_break_out_of_the_string_literal():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).list_open_projects("x' OR Name != '")

    assert f"{sf.PROJECT_ACCOUNT_FIELD} = 'x\\' OR Name != \\'' AND " in _soql(transport.requests[1])


def test_account_without_open_projects_returns_an_empty_list():
    transport = _FakeTransport(_token(), _query_result())

    assert sf.SalesforceClient(_creds(), opener=transport).list_open_projects("001AA000001AAAAIA2") == []


def test_blank_account_id_returns_nothing_without_asking_salesforce():
    transport = _FakeTransport()

    assert sf.SalesforceClient(_creds(), opener=transport).list_open_projects("  ") == []
    assert transport.requests == []


def test_network_error_while_listing_projects_raises_network_error():
    transport = _FakeTransport(_token(), urllib.error.URLError("Network is unreachable"))

    with pytest.raises(sf.SalesforceNetworkError):
        sf.SalesforceClient(_creds(), opener=transport).list_open_projects("001AA000001AAAAIA2")


def test_org_error_while_listing_projects_carries_the_salesforce_text():
    transport = _FakeTransport(_token(), _http_error(400, [
        {"message": "No such column 'Status__c' on entity 'Project__c'.", "errorCode": "INVALID_FIELD"},
    ]))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).list_open_projects("001AA000001AAAAIA2")

    assert "No such column" in str(excinfo.value)


# ---------- Welche Salesforce-Projekte sind noch offen? (Abgleich, Prüfung vor dem Buchen) ----------

_RELAUNCH_ID = "a0XAA000001AAAAIA2"
_WARTUNG_ID = "a0XAA000001BBBBIA2"
_GELOESCHT_ID = "a0XAA000001CCCCIA2"


def test_open_projects_among_returns_those_that_are_still_open():
    # Salesforce answers only with the offenen ones: closed and deleted Projekte are simply missing
    transport = _FakeTransport(_token(), _query_result({"Id": _RELAUNCH_ID}))

    still_open = sf.SalesforceClient(_creds(), opener=transport).open_projects_among(
        [_RELAUNCH_ID, _WARTUNG_ID, _GELOESCHT_ID]
    )

    assert still_open == {_RELAUNCH_ID}


def test_open_projects_among_asks_for_exactly_these_projects_and_only_the_open_ones():
    transport = _FakeTransport(_token(), _query_result())

    sf.SalesforceClient(_creds(), opener=transport).open_projects_among([f" {_RELAUNCH_ID} ", _WARTUNG_ID])

    assert _soql(transport.requests[1]) == (
        f"SELECT Id FROM {sf.PROJECT_OBJECT} "
        f"WHERE Id IN ('{_RELAUNCH_ID}', '{_WARTUNG_ID}') "
        f"AND {sf.PROJECT_STATUS_FIELD} IN ({_OPEN_STATUSES})"
    )


def test_a_15_character_id_is_recognised_in_the_18_character_answer():
    # hand-typed references may be the 15-character form; Salesforce always answers with 18
    transport = _FakeTransport(_token(), _query_result({"Id": _RELAUNCH_ID}))

    still_open = sf.SalesforceClient(_creds(), opener=transport).open_projects_among(
        [_RELAUNCH_ID[:15], _WARTUNG_ID[:15]]
    )

    assert still_open == {_RELAUNCH_ID[:15]}


def test_references_that_are_no_salesforce_id_count_as_closed_and_never_reach_the_query():
    # typed by hand before Registrieren existed; one malformed ID would make Salesforce refuse the whole query
    transport = _FakeTransport(_token(), _query_result({"Id": _RELAUNCH_ID}))

    still_open = sf.SalesforceClient(_creds(), opener=transport).open_projects_among(
        ["Relaunch 2024", "x') OR Name != ('", _RELAUNCH_ID, ""]
    )

    assert still_open == {_RELAUNCH_ID}
    assert _soql(transport.requests[1]).count("'") == 2 + 2 * len(sf.PROJECT_OPEN_STATUSES)   # the one ID and the open statuses


def test_nothing_to_check_returns_nothing_without_asking_salesforce():
    transport = _FakeTransport()
    client = sf.SalesforceClient(_creds(), opener=transport)

    assert client.open_projects_among([]) == set()
    assert client.open_projects_among(["kein-salesforce-projekt"]) == set()
    assert transport.requests == []


def _many_project_ids(count: int) -> list[str]:
    return [f"a0XAA{number:010d}IA2" for number in range(count)]


def test_many_projects_are_asked_for_in_blocks_that_fit_into_a_request():
    # the query travels in the URL of a GET; Salesforce refuses URLs beyond 16,384 bytes
    ids = _many_project_ids(450)
    first, last = ids[0], ids[-1]
    transport = _FakeTransport(
        _token(), _query_result({"Id": first}), _query_result(), _query_result({"Id": last}),
    )

    still_open = sf.SalesforceClient(_creds(), opener=transport).open_projects_among(ids)

    assert still_open == {first, last}
    queries = transport.requests[1:]
    assert len(queries) == 3
    assert all(len(req.full_url) < 8000 for req in queries)
    asked = [i for req in queries for i in ids if f"'{i}'" in _soql(req)]
    assert sorted(asked) == ids   # every Projekt exactly once


def test_the_same_project_in_both_id_forms_is_asked_for_once():
    transport = _FakeTransport(_token(), _query_result({"Id": _RELAUNCH_ID}))

    still_open = sf.SalesforceClient(_creds(), opener=transport).open_projects_among(
        [_RELAUNCH_ID, _RELAUNCH_ID[:15], _RELAUNCH_ID]
    )

    assert still_open == {_RELAUNCH_ID, _RELAUNCH_ID[:15]}
    assert _soql(transport.requests[1]).count("a0XAA000001AAAA") == 1


def test_network_error_while_checking_open_projects_raises_network_error():
    transport = _FakeTransport(_token(), urllib.error.URLError("Network is unreachable"))

    with pytest.raises(sf.SalesforceNetworkError):
        sf.SalesforceClient(_creds(), opener=transport).open_projects_among([_RELAUNCH_ID])


def test_an_error_in_a_later_block_fails_the_whole_check_instead_of_reporting_projects_as_closed():
    ids = _many_project_ids(450)
    transport = _FakeTransport(_token(), _query_result({"Id": ids[0]}), _http_error(500, [
        {"message": "Server busy", "errorCode": "SERVER_UNAVAILABLE"},
    ]))

    with pytest.raises(sf.SalesforceOrgError) as excinfo:
        sf.SalesforceClient(_creds(), opener=transport).open_projects_among(ids)

    assert "Server busy" in str(excinfo.value)
