from __future__ import annotations

from worklog import repository as repo
from worklog.services import credentials
from worklog.services import salesforce_settings as sfs


def _configure(conn, url="https://acme.my.salesforce.com", key="key-123"):
    repo.set_setting(conn, sfs.SETTINGS_SF_INSTANCE_URL, url)
    repo.set_setting(conn, sfs.SETTINGS_SF_CONSUMER_KEY, key)


def test_nothing_configured_names_everything_that_is_missing(conn):
    config = sfs.load_configuration(conn, get_secret=lambda: None)

    assert not config.is_complete
    assert config.missing == ["Instance-URL", "Consumer Key", "Consumer Secret"]
    assert config.credentials is None


def test_complete_configuration_yields_credentials(conn):
    _configure(conn, url="  https://acme.my.salesforce.com ")

    config = sfs.load_configuration(conn, get_secret=lambda: "s3cret")

    assert config.is_complete
    assert config.missing == []
    assert config.missing_text == ""
    assert config.credentials.instance_url == "https://acme.my.salesforce.com"
    assert config.credentials.consumer_key == "key-123"
    assert config.credentials.consumer_secret == "s3cret"


def test_only_the_secret_missing_is_named(conn):
    _configure(conn)

    config = sfs.load_configuration(conn, get_secret=lambda: None)

    assert not config.is_complete
    assert config.missing == ["Consumer Secret"]
    assert "Consumer Secret" in config.missing_text


def test_unreachable_keyring_is_reported_as_missing_with_reason(conn):
    _configure(conn)

    def unreachable():
        raise credentials.CredentialsUnavailableError("no backend")

    config = sfs.load_configuration(conn, get_secret=unreachable)

    assert not config.is_complete
    assert len(config.missing) == 1
    assert "Keyring" in config.missing[0]
    assert "no backend" in config.missing[0]

