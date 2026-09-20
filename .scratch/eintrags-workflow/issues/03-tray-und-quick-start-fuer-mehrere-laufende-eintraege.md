# 03: Tray und Quick-Start für mehrere laufende Einträge

**What to build:** Ein Klick auf das Tray-Icon öffnet immer das Quick-Start-Popup, mit dem ich einen weiteren Eintrag starte. Das Tray-Menü listet alle laufenden Einträge; jeden kann ich einzeln stoppen, und "Alle stoppen" beendet alles auf einmal. Das Icon zeigt "läuft", sobald mindestens ein Eintrag läuft, der Tooltip nennt die Anzahl. Das Quick-Add-Popup kennt nur noch den Modus Start; "Aktuellen Eintrag bearbeiten" und "Task wechseln" gibt es nicht mehr.

Dies ist der Contract-Schritt zu Ticket 02: Danach ist die alte Ein-Timer-Schnittstelle des Timer-Service entfernt.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 9–13).

**Blocked by:** 02 (Mehrere laufende Einträge im Timer-Tab)

**Status:** ready-for-agent

- [x] Klick auf das Tray-Icon öffnet das Quick-Start-Popup, unabhängig davon, ob etwas läuft.
- [x] Das Tray-Menü zeigt pro laufendem Eintrag einen Punkt (Projekt, Task bzw. Beschreibung erkennbar), der genau diesen Eintrag stoppt.
- [x] "Alle stoppen" erscheint, sobald mindestens ein Eintrag läuft, und stoppt alle mit korrekter Rundung.
- [x] Icon-Zustand "läuft" ab einem laufenden Eintrag; Tooltip nennt die Anzahl laufender Einträge.
- [x] Die bestehenden Menüpunkte zum erneuten Starten zuletzt verwendeter Tasks starten einen zusätzlichen Eintrag und stoppen nichts.
- [x] Das Quick-Add-Popup hat nur noch den Modus Start; ein blockierter Doppelstart zeigt "läuft bereits".
- [x] Ein eventuell vorhandener globaler Hotkey öffnet Quick-Start statt einen Timer umzuschalten.
  - Es gibt keinen globalen Hotkey in der App; `worklog --quick` (IPC) öffnet Quick-Start, der Mittelklick aufs Tray-Icon ebenfalls (schaltet nichts mehr um).
- [x] Die alte Ein-Timer-Schnittstelle (aktueller Eintrag, wechseln, laufenden Eintrag aktualisieren, Stoppen ohne ID) ist entfernt; kein Aufrufer liest oder schreibt mehr den Einzelzeiger im App-Zustand.
  - Offen: `current`, `is_running`, `stop()` ohne ID, `update_running`, `switch` sind entfernt; den Einzelzeiger liest oder schreibt kein Aufrufer mehr. Übrig ist nur `TimerService.start()`, weil das Fortsetzen im Logs-Tab (`logs_view._resume`) es noch aufruft; das Entfernen gehört zu Ticket 04.
- [x] Timer-Tab, Tray-Menü und Logs-Tab bleiben nach Start/Stopp aus jeder dieser Stellen synchron.
- [ ] Tests laufen grün; Tray und Popup sind von Hand geprüft.
  - Offen: `uv run pytest` ist grün; Tray und Popup sind nur offscreen per Skript geprüft (Menü mit 0/1/3 laufenden Einträgen, Einzel-Stop, Alle stoppen, Tooltip, Quick-Start, blockierter Doppelstart), nicht von Hand an einem echten Tray.
