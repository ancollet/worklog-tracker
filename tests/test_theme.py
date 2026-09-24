from PyQt6.QtWidgets import QLabel

from worklog.ui import theme


def test_light_and_dark_define_the_same_tokens():
    assert theme.LIGHT.keys() == theme.DARK.keys()


def test_old_qt_material_values_map_to_light_or_dark(qapp):
    assert theme.resolve_theme(qapp, "dark_teal.xml") == theme.DARK_THEME
    assert theme.resolve_theme(qapp, "light_blue.xml") == theme.LIGHT_THEME
    assert theme.resolve_theme(qapp, "none") in (theme.LIGHT_THEME, theme.DARK_THEME)


def test_apply_theme_switches_the_colour_tokens(qapp):
    try:
        theme.apply_theme(qapp, theme.DARK_THEME)
        assert theme.color("bg") == theme.DARK["bg"]
        assert theme.DARK["accent"] in qapp.styleSheet()
        theme.apply_theme(qapp, theme.LIGHT_THEME)
        assert theme.color("bg") == theme.LIGHT["bg"]
    finally:
        qapp.setStyleSheet("")


def test_every_accent_overrides_the_same_tokens():
    for _label, light, dark in theme.ACCENTS.values():
        assert light.keys() == dark.keys() == {"accent", "accent_hover", "accent_soft"}


def test_old_qt_material_values_keep_their_accent_colour():
    assert theme.resolve_accent("dark_teal.xml", None) == "teal"
    assert theme.resolve_accent("light_blue.xml", None) == "blue"
    assert theme.resolve_accent("dark_teal.xml", "pink") == "pink"
    assert theme.resolve_accent("system", None) == theme.DEFAULT_ACCENT
    assert theme.resolve_accent("system", "gone") == theme.DEFAULT_ACCENT


def test_apply_theme_uses_the_chosen_accent(qapp):
    try:
        theme.apply_theme(qapp, theme.DARK_THEME, "teal")
        assert theme.color("accent") == theme.ACCENTS["teal"][2]["accent"]
        assert theme.color("bg") == theme.DARK["bg"]
        theme.apply_theme(qapp, theme.LIGHT_THEME, "teal")
        assert theme.color("accent") == theme.ACCENTS["teal"][1]["accent"]
    finally:
        qapp.setStyleSheet("")


def test_set_status_gives_the_label_a_role(qapp):
    label = QLabel("x")
    theme.set_status(label, "error")
    assert label.property("role") == "hint-error"
    theme.set_status(label)
    assert label.property("role") == "hint"
