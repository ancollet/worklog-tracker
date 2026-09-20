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
    assert config.missing == ["Instance-URL", "Consumer Key", "Consumer Secret", "Leistende Person"]
    assert config.credentials is None


def test_complete_configuration_yields_credentials(conn):
    _configure(conn, url="  https://acme.my.salesforce.com ")
    sfs.save_leistende_person(conn, sfs.LeistendePerson("005A", "Anna Collet"))

    config = sfs.load_configuration(conn, get_secret=lambda: "s3cret")

    assert config.is_complete
    assert config.missing == []
    assert config.missing_text == ""
    assert config.credentials.instance_url == "https://acme.my.salesforce.com"
    assert config.credentials.consumer_key == "key-123"
    assert config.credentials.consumer_secret == "s3cret"


def test_only_the_secret_missing_is_named(conn):
    _configure(conn)
    sfs.save_leistende_person(conn, sfs.LeistendePerson("005A", "Anna Collet"))

    config = sfs.load_configuration(conn, get_secret=lambda: None)

    assert not config.is_complete
    assert config.missing == ["Consumer Secret"]
    assert "Consumer Secret" in config.missing_text


def test_unreachable_keyring_is_reported_as_missing_with_reason(conn):
    _configure(conn)
    sfs.save_leistende_person(conn, sfs.LeistendePerson("005A", "Anna Collet"))

    def unreachable():
        raise credentials.CredentialsUnavailableError("no backend")

    config = sfs.load_configuration(conn, get_secret=unreachable)

    assert not config.is_complete
    assert len(config.missing) == 1
    assert "Keyring" in config.missing[0]
    assert "no backend" in config.missing[0]


# ---- leistende Person ----

def test_no_leistende_person_by_default(conn):
    assert sfs.load_leistende_person(conn) is None


def test_leistende_person_round_trips_through_the_settings_table(conn):
    sfs.save_leistende_person(
        conn, sfs.LeistendePerson(id="005AA0000012345IAA", name="Anna Collet", email="anna@example.com")
    )

    person = sfs.load_leistende_person(conn)

    assert person == sfs.LeistendePerson("005AA0000012345IAA", "Anna Collet", "anna@example.com")
    assert repo.get_setting(conn, sfs.SETTINGS_SF_PERSON_ID) == "005AA0000012345IAA"
    assert repo.get_setting(conn, sfs.SETTINGS_SF_PERSON_NAME) == "Anna Collet"


def test_display_text_shows_name_and_email_but_never_the_id(conn):
    with_email = sfs.LeistendePerson("005AA0000012345IAA", "Anna Collet", "anna@example.com")
    without_email = sfs.LeistendePerson("005AA0000012345IAA", "Anna Collet")

    assert with_email.display_text == "Anna Collet (anna@example.com)"
    assert without_email.display_text == "Anna Collet"


def test_leistende_person_can_be_changed_and_removed(conn):
    sfs.save_leistende_person(conn, sfs.LeistendePerson("005A", "Anna Collet", "anna@example.com"))
    sfs.save_leistende_person(conn, sfs.LeistendePerson("005B", "Ben Roth"))

    assert sfs.load_leistende_person(conn) == sfs.LeistendePerson("005B", "Ben Roth", "")

    sfs.save_leistende_person(conn, None)

    assert sfs.load_leistende_person(conn) is None
    assert repo.get_setting(conn, sfs.SETTINGS_SF_PERSON_ID) is None
    assert repo.get_setting(conn, sfs.SETTINGS_SF_PERSON_NAME) is None


def test_connection_without_leistende_person_allows_registering_but_not_booking(conn):
    _configure(conn)

    config = sfs.load_configuration(conn, get_secret=lambda: "s3cret")

    assert config.is_connection_complete      # Registrieren
    assert config.credentials is not None
    assert not config.is_complete             # Buchen
    assert config.missing == ["Leistende Person"]
    assert config.missing_connection == []
    assert config.connection_missing_text == ""
    assert "Leistende Person" in config.missing_text
    assert config.leistende_person is None


def test_leistende_person_without_connection_names_both(conn):
    sfs.save_leistende_person(conn, sfs.LeistendePerson("005A", "Anna Collet"))

    config = sfs.load_configuration(conn, get_secret=lambda: None)

    assert not config.is_connection_complete
    assert not config.is_complete
    assert config.missing == ["Instance-URL", "Consumer Key", "Consumer Secret"]
    assert "Instance-URL" in config.connection_missing_text
    assert config.leistende_person == sfs.LeistendePerson("005A", "Anna Collet")


def test_loading_the_configuration_never_needs_the_network(conn, monkeypatch):
    import urllib.request

    def no_network(*a, **kw):
        raise AssertionError("network touched")

    monkeypatch.setattr(urllib.request, "urlopen", no_network)
    _configure(conn)
    sfs.save_leistende_person(conn, sfs.LeistendePerson("005A", "Anna Collet"))

    assert sfs.load_configuration(conn, get_secret=lambda: "s3cret").is_complete


# ---------- Globaler Default für den Service Type ----------


def test_default_service_type_is_consulting_until_i_choose_one(conn):
    assert sfs.SERVICE_TYPES == ("Consulting", "Development")
    assert sfs.load_default_service_type(conn) == "Consulting"


def test_chosen_default_service_type_is_remembered(conn):
    sfs.save_default_service_type(conn, "Development")

    assert sfs.load_default_service_type(conn) == "Development"


def test_unknown_service_type_is_refused_and_a_broken_setting_falls_back(conn):
    import pytest

    with pytest.raises(ValueError):
        sfs.save_default_service_type(conn, "Training")

    repo.set_setting(conn, sfs.SETTINGS_SF_DEFAULT_SERVICE_TYPE, "Training")
    assert sfs.load_default_service_type(conn) == "Consulting"
