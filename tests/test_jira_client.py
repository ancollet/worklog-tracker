from __future__ import annotations

import io
import json
import urllib.error
from datetime import datetime, timezone, timedelta

import pytest

from worklog.services import jira as j


def test_extract_issue_key_basic():
    assert j.extract_issue_key("DIS-1234") == "DIS-1234"
    assert j.extract_issue_key("fix DIS-1234 today") == "DIS-1234"
    assert j.extract_issue_key("PROJ-1") == "PROJ-1"
    assert j.extract_issue_key("ABC1-99") == "ABC1-99"


def test_extract_issue_key_first_match_wins():
    assert j.extract_issue_key("link to FOO-1 and BAR-2") == "FOO-1"


def test_extract_issue_key_no_match():
    assert j.extract_issue_key(None) is None
    assert j.extract_issue_key("") is None
    assert j.extract_issue_key("dis-1234") is None  # must be upper-case
    assert j.extract_issue_key("12-34") is None
    assert j.extract_issue_key("FIX-") is None


def test_format_started_includes_millis_and_offset():
    dt = datetime(2026, 5, 13, 10, 0, 0, 0, tzinfo=timezone(timedelta(hours=2)))
    s = j.format_started(dt)
    assert s == "2026-05-13T10:00:00.000+0200"


def test_format_started_uses_local_tz_when_naive():
    dt = datetime(2026, 5, 13, 10, 0, 0)
    s = j.format_started(dt)
    # offset suffix is present and has the +HHMM form
    assert s[:23] == "2026-05-13T10:00:00.000"
    assert s[23] in ("+", "-")
    assert len(s[23:]) == 5


class _FakeResponse:
    def __init__(self, payload: dict, status: int = 201) -> None:
        self._body = json.dumps(payload).encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_add_worklog_success_returns_id_and_url():
    captured = {}

    def fake_opener(req, timeout=15):
        captured["url"] = req.full_url
        captured["method"] = req.get_method()
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"id": "10001", "self": "https://acme.atlassian.net/rest/api/3/issue/DIS-1/worklog/10001"})

    creds = j.JiraCredentials(
        base_url="https://acme.atlassian.net/",  # trailing slash should be normalized
        email="me@acme.com",
        api_token="tok",
    )
    started = datetime(2026, 5, 13, 10, 0, tzinfo=timezone(timedelta(hours=2)))
    result = j.add_worklog(
        creds, issue_key="DIS-1234",
        started=started, time_spent_seconds=3600,
        comment="lunch fix", opener=fake_opener,
    )

    assert result.worklog_id == "10001"
    assert result.issue_key == "DIS-1234"
    assert result.issue_browse_url == "https://acme.atlassian.net/browse/DIS-1234"
    assert captured["url"] == "https://acme.atlassian.net/rest/api/3/issue/DIS-1234/worklog"
    assert captured["method"] == "POST"
    # auth header capitalization is normalized by Request
    auth = {k.lower(): v for k, v in captured["headers"].items()}
    assert auth["authorization"].startswith("Basic ")
    body = captured["body"]
    assert body["timeSpentSeconds"] == 3600
    assert body["started"] == "2026-05-13T10:00:00.000+0200"
    assert body["comment"]["type"] == "doc"


def test_add_worklog_no_comment_omits_field():
    captured = {}

    def fake_opener(req, timeout=15):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return _FakeResponse({"id": "1"})

    creds = j.JiraCredentials("https://x.atlassian.net", "a@b", "t")
    j.add_worklog(creds, issue_key="X-1", started=datetime.now(timezone.utc),
                  time_spent_seconds=60, opener=fake_opener)
    assert "comment" not in captured["body"]


def test_add_worklog_rejects_zero_duration():
    creds = j.JiraCredentials("https://x.atlassian.net", "a@b", "t")
    with pytest.raises(ValueError):
        j.add_worklog(creds, issue_key="X-1", started=datetime.now(timezone.utc),
                      time_spent_seconds=0, opener=lambda r, timeout=15: None)


def _http_error(code: int, body: bytes = b""):
    return urllib.error.HTTPError(
        url="https://x", code=code, msg="err", hdrs=None, fp=io.BytesIO(body),
    )


def test_add_worklog_401_raises_auth_error():
    def fake_opener(req, timeout=15):
        raise _http_error(401, b'{"errorMessages":["bad cred"]}')

    creds = j.JiraCredentials("https://x.atlassian.net", "a@b", "t")
    with pytest.raises(j.JiraAuthError):
        j.add_worklog(creds, issue_key="X-1", started=datetime.now(timezone.utc),
                      time_spent_seconds=60, opener=fake_opener)


def test_add_worklog_404_raises_not_found():
    def fake_opener(req, timeout=15):
        raise _http_error(404)

    creds = j.JiraCredentials("https://x.atlassian.net", "a@b", "t")
    with pytest.raises(j.JiraNotFoundError):
        j.add_worklog(creds, issue_key="MISSING-1", started=datetime.now(timezone.utc),
                      time_spent_seconds=60, opener=fake_opener)


def test_add_worklog_network_error_raises_generic():
    def fake_opener(req, timeout=15):
        raise urllib.error.URLError("DNS down")

    creds = j.JiraCredentials("https://x.atlassian.net", "a@b", "t")
    with pytest.raises(j.JiraError):
        j.add_worklog(creds, issue_key="X-1", started=datetime.now(timezone.utc),
                      time_spent_seconds=60, opener=fake_opener)
