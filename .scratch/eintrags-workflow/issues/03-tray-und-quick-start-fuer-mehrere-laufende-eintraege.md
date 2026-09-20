# 03: Tray und Quick-Start für mehrere laufende Einträge

**What to build:** Ein Klick auf das Tray-Icon öffnet immer das Quick-Start-Popup, mit dem ich einen weiteren Eintrag starte. Das Tray-Menü listet alle laufenden Einträge; jeden kann ich einzeln stoppen, und "Alle stoppen" beendet alles auf einmal. Das Icon zeigt "läuft", sobald mindestens ein Eintrag läuft, der Tooltip nennt die Anzahl. Das Quick-Add-Popup kennt nur noch den Modus Start; "Aktuellen Eintrag bearbeiten" und "Task wechseln" gibt es nicht mehr.

Dies ist der Contract-Schritt zu Ticket 02: Danach ist die alte Ein-Timer-Schnittstelle des Timer-Service entfernt.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 9–13).

**Blocked by:** 02 (Mehrere laufende Einträge im Timer-Tab)

**Status:** ready-for-agent

- [ ] Klick auf das Tray-Icon öffnet das Quick-Start-Popup, unabhängig davon, ob etwas läuft.
- [ ] Das Tray-Menü zeigt pro laufendem Eintrag einen Punkt (Projekt, Task bzw. Beschreibung erkennbar), der genau diesen Eintrag stoppt.
- [ ] "Alle stoppen" erscheint, sobald mindestens ein Eintrag läuft, und stoppt alle mit korrekter Rundung.
- [ ] Icon-Zustand "läuft" ab einem laufenden Eintrag; Tooltip nennt die Anzahl laufender Einträge.
- [ ] Die bestehenden Menüpunkte zum erneuten Starten zuletzt verwendeter Tasks starten einen zusätzlichen Eintrag und stoppen nichts.
- [ ] Das Quick-Add-Popup hat nur noch den Modus Start; ein blockierter Doppelstart zeigt "läuft bereits".
- [ ] Ein eventuell vorhandener globaler Hotkey öffnet Quick-Start statt einen Timer umzuschalten.
- [ ] Die alte Ein-Timer-Schnittstelle (aktueller Eintrag, wechseln, laufenden Eintrag aktualisieren, Stoppen ohne ID) ist entfernt; kein Aufrufer liest oder schreibt mehr den Einzelzeiger im App-Zustand.
- [ ] Timer-Tab, Tray-Menü und Logs-Tab bleiben nach Start/Stopp aus jeder dieser Stellen synchron.
- [ ] Tests laufen grün; Tray und Popup sind von Hand geprüft.
