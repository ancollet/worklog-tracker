# Worklog

Time-Tracker / Worklog-App für Ubuntu und Windows (PyQt6 + SQLite).

- Kunden + Projekte mit optionaler projektspezifischer Rundung
- Live-Timer mit Tasks (Jira-Style: `PROJ-123`) und Beschreibung, Auto-Vervollständigung
- Manuelle Logs: Start/End-Zeit *oder* Datum + Dauer
- Aufrunden auf 0/5/10/15/30/60 min, global oder pro Projekt
- System-Tray mit Quick-Add-Popup, Recent-Tasks, Edit/Switch
- Analytics: Tag/Woche/Monat × Projekt/Kunde, Tabelle + Chart, CSV-Export
- Salesforce-Anbindung: Kunden/Projekte registrieren, Zeiten als Kostenposition buchen und stornieren

## Releases

Fertige Pakete liegen unter [Releases](https://github.com/ancollet/worklog-tracker/releases):

| Datei | Installation |
|---|---|
| `worklog_X.Y.Z_amd64.deb` | `sudo apt install ./worklog_X.Y.Z_amd64.deb` (Ubuntu 22.04+) |
| `WorklogSetup.exe` | Doppelklick, installiert ohne Admin-Rechte nach `%LocalAppData%\Programs\Worklog` |
| `Worklog-X.Y.Z-arm64.dmg` | Öffnen, `Worklog.app` nach `Applications` ziehen (Apple Silicon) |

Das `.exe` ist nicht signiert: SmartScreen warnt beim ersten Start einmalig
(„Weitere Informationen“ → „Trotzdem ausführen“).
Die `.app` ist ebenfalls nicht signiert: beim ersten Start Rechtsklick → „Öffnen“, oder
`xattr -d com.apple.quarantine /Applications/Worklog.app`.

## Voraussetzungen und Dev-Setup

- [`uv`](https://docs.astral.sh/uv/); Python 3.11+ installiert uv bei Bedarf selbst

```bash
uv sync --extra dev   # .venv anlegen, Worklog editable + Dev-Dependencies
uv run worklog        # App starten
uv run worklog --quick  # Quick-Add-Popup öffnen (läuft die App schon: dort)
uv run pytest         # Tests
```

Daten liegen in `~/.local/share/worklog/worklog.db` (XDG) bzw. `%APPDATA%\worklog`.

Ohne Paket als Daily-Driver installieren (uv tool + Icon + `.desktop`):
`./packaging/install.sh`, entfernen mit `./packaging/uninstall.sh`.
Achtung: Worklog läuft als Single-Instance im Tray, nach einem Update die alte Instanz beenden.

## Release erstellen

1. Version in `pyproject.toml` und `worklog/__init__.py` hochziehen, committen, pushen.
2. Release mit Tag anlegen:
   ```bash
   gh release create vX.Y.Z --generate-notes
   ```
3. `.github/workflows/release.yml` baut `.deb` (ubuntu-22.04), `WorklogSetup.exe`
   (windows-latest, Inno Setup) und `.dmg` (macos-latest) und hängt alle drei an den Release.

„Run workflow“ auf der Actions-Seite baut beides ohne Release als Artefakte (Version aus `pyproject.toml`).

Lokal bauen:

```bash
./packaging/linux/build-deb.sh 0.1.0                              # braucht dpkg-deb
./packaging/macos/build-dmg.sh 0.1.0                              # auf macOS
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1  # Windows, dann:
iscc packaging\windows\installer.iss                              # -> packaging\windows\output\WorklogSetup.exe
```
