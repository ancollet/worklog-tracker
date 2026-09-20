# Worklog

Time-Tracker / Worklog-App für Ubuntu (PyQt6 + SQLite).

Features:
- Kunden + Projekte mit optionaler Projekt-spezifischer Rundung
- Live-Timer mit Tasks (Jira-Style: `PROJ-123`) und Beschreibung
- Auto-Vervollständigung früherer Tasks und Beschreibungen
- Manuelle Logs in zwei Modi: Start/End-Zeit *oder* Datum + Dauer
- Aufrunden auf 0/5/10/15/30/60 min, global oder pro Projekt überschreibbar
- System-Tray mit Quick-Add-Popup, Recent-Tasks, Edit/Switch
- Analytics: Tag/Woche/Monat × Projekt/Kunde, Tabelle + Stacked-Bar-Chart, CSV-Export

## Voraussetzungen

- [`uv`](https://docs.astral.sh/uv/) (Package-Manager)
- Python 3.11+ (uv installiert es bei Bedarf automatisch)

## Installation (Daily-Driver)

Für den täglichen Einsatz: `worklog` global verfügbar machen, Icon ins Dock,
`.desktop`-Eintrag im App-Launcher:

```bash
./packaging/install.sh
```

Was passiert:
- `uv tool install` legt den `worklog`-CLI nach `~/.local/bin/`
- SVG-Icon wandert nach `~/.local/share/icons/hicolor/scalable/apps/`
- `.desktop`-Eintrag (mit Action **Quick Add**) nach `~/.local/share/applications/`

Updaten: `git pull && ./packaging/install.sh` (idempotent via `--reinstall`).
Deinstallieren: `./packaging/uninstall.sh` (Datenverzeichnis bleibt erhalten).

## Dev-Setup

```bash
uv sync --extra dev
```

`uv sync` legt `.venv/` an, installiert Worklog im Editable-Modus inkl. Dev-Dependencies und schreibt `uv.lock`.

## Starten (Dev)

```bash
uv run worklog
```

Oder explizit:
```bash
uv run python -m worklog
```

Daten landen in `~/.local/share/worklog/worklog.db` (XDG).

Mit dem Flag `--quick` öffnet sich direkt das Quick-Add-Popup, falls die App schon läuft:
```bash
uv run worklog --quick
```
(Lässt sich auf einen globalen Hotkey im Desktop-Environment binden.)

## Tests

```bash
uv run pytest
```

Optional verbose:
```bash
uv run pytest -v
```

## Tastenkürzel im Hauptfenster

| Shortcut | Aktion |
|----------|--------|
| `Ctrl+S` | Neuen Eintrag aus dem Formular starten (stoppt nichts) |
| `Ctrl+N` | Timer-Tab fokussieren |
| `Ctrl+L` | Add-Log-Dialog |

## Tray / Panel-Applet

Linksklick auf das Tray-Icon öffnet immer das frameless Quick-Add-Popup
direkt am Panel — fungiert damit als minimales Tracking-Applet:

- **Start ▶** (idle) bzw. **Wechseln ↻** (running) — startet/wechselt Task
- **⏸ Stop** — beendet den aktiven Timer (nur sichtbar wenn läuft)
- **⏰ Stunden nachtragen…** — öffnet den manuellen Log-Dialog

| Aktion | Verhalten |
|--------|-----------|
| Linksklick | Quick-Add-Popup (mit Stop/Add-Hours-Buttons) |
| Mittelklick | Timer toggeln |
| Rechtsklick | Kontextmenü mit Recent Tasks, Edit, Switch, Settings |

## Projektstruktur

```
worklog/
  app.py               Entry: QApplication + Single-Instance + Tray-Wiring
  db.py                SQLite-Schema + Migrationen
  models.py            Dataclasses
  repository.py        Alle Queries (UI berührt SQL nie direkt)
  paths.py             XDG-Pfade
  services/
    timer.py           TimerService: start/stop, persistente Running-Entry
    rounding.py        round_up_seconds + Format-Helper
    analytics.py       Aggregations-Queries
  ui/
    main_window.py     Tabs: Timer | Logs | Kunden | Analytics
    timer_widget.py    Live-Timer
    log_dialog.py      Add/Edit-Log mit zwei Modi
    logs_view.py       Logs-Tabelle
    customers_view.py  Kunden/Projekte-Tree
    analytics_view.py  Analytics + Bar-Chart
    settings_dialog.py Default-Rundung, Default-Projekt, Autostart
    tray.py            System-Tray
    quick_add.py       Frameless Quick-Add-Popup
    completers.py      DB-backed QCompleter
tests/                 Pytest-Suite (rounding, repository, timer, analytics)
```
