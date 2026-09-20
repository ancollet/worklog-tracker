# 01: Gemeinsames Eintrags-Kontextmenü (Prefactor)

**What to build:** Der Baum im Timer-Tab und die Tabelle im Logs-Tab bauen ihr Rechtsklick-Menü heute getrennt und unterschiedlich auf; die Tabelle kennt nur Einzelauswahl. Nach diesem Ticket entsteht das Menü für Einträge an genau einer Stelle, die eine geordnete Liste der betroffenen Einträge bekommt und daraus die Menüpunkte ableitet. Beide Ansichten nutzen sie, beide unterstützen Mehrfachauswahl. Für den Nutzer ändert sich sichtbar nichts außer, dass der Logs-Tab nun dieselben Punkte wie der Timer-Tab anbietet (Flags, Sammel-Löschen) und der Timer-Tab die Buchungspunkte des Logs-Tabs. Spätere Tickets hängen neue Menüpunkte nur noch an dieser einen Stelle ein.

Spec: `.scratch/eintrags-workflow/spec.md` (Abschnitt "Übergreifend").

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Es gibt genau einen Ort, der das Kontextmenü für eine Auswahl von Einträgen aufbaut; Baum und Tabelle rufen ihn auf.
- [ ] Rechtsklick auf einen nicht selektierten Eintrag wirkt nur auf diesen, ohne die Auswahl zu verändern; Rechtsklick auf einen selektierten Eintrag wirkt auf die ganze Auswahl (heutiges Verhalten des Baums, jetzt auch in der Tabelle).
- [ ] Die Tabelle im Logs-Tab erlaubt Mehrfachauswahl.
- [ ] Alle heutigen Menüpunkte bleiben erhalten und funktionieren in beiden Ansichten: Bearbeiten (nur bei genau einem Eintrag), Flags-Untermenü inkl. "gemischt"-Anzeige und "Flags verwalten…", Jira buchen bzw. Jira-Buchung lokal entfernen (nur bei genau einem Eintrag eines Jira-Kunden), Löschen einzeln und gesammelt mit Rückfrage.
- [ ] Das bisherige "Fortsetzen" im Logs-Tab (Button und Menüpunkt) funktioniert unverändert weiter; es wird in Ticket 04 umgebaut.
- [ ] Nach jeder Aktion aus dem Menü sind beide Ansichten und die Summen aktuell.
- [ ] Bestehende Tests laufen grün (`uv run pytest`); die App startet und beide Menüs sind von Hand geprüft.
