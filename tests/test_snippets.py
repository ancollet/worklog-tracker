from worklog.services.snippets import apply_snippet

KNOWN = ["Codereview", "Entwicklung", "Istanalyse", "Recherche"]


def test_empty_description_becomes_snippet_prefix():
    assert apply_snippet("", "Codereview", KNOWN) == "Codereview: "


def test_description_without_prefix_gets_snippet_prefix():
    assert apply_snippet("Login-Formular", "Codereview", KNOWN) == "Codereview: Login-Formular"


def test_second_snippet_is_appended_to_existing_prefix():
    assert (
        apply_snippet("Codereview: Login-Formular", "Recherche", KNOWN)
        == "Codereview, Recherche: Login-Formular"
    )


def test_colon_in_free_text_is_not_a_prefix():
    assert apply_snippet("Fix: Login", "Codereview", KNOWN) == "Codereview: Fix: Login"


def test_snippet_already_in_prefix_changes_nothing():
    assert (
        apply_snippet("Codereview: Login-Formular", "Codereview", KNOWN)
        == "Codereview: Login-Formular"
    )


def test_duplicate_check_ignores_case():
    assert (
        apply_snippet("codereview, Recherche: Login", "CODEREVIEW", KNOWN)
        == "codereview, Recherche: Login"
    )


def test_prefix_with_unknown_part_is_free_text():
    assert (
        apply_snippet("Codereview, Fix: Login", "Recherche", KNOWN)
        == "Recherche: Codereview, Fix: Login"
    )


def test_second_snippet_on_prefix_only_description():
    assert apply_snippet("Codereview: ", "Recherche", KNOWN) == "Codereview, Recherche: "
