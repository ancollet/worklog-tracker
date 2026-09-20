# 07: Gebucht = gesperrt und "Buchung stornieren"

**What to build:** Sobald ein Eintrag gebucht ist, kann ich ihn nicht mehr bearbeiten, löschen, verschieben oder bereinigen; ich bekomme die klare Meldung "Eintrag ist gebucht, erst Buchung stornieren". Flags setzen (z.B. "abgerechnet"), Fortsetzen und Beschreibung kopieren gehen weiterhin. Über "Buchung stornieren" im Kontextmenü gebe ich den Eintrag wieder frei. Das gilt einheitlich für alle Buchungssysteme; dieses Ticket liefert es für die bestehenden Jira-Buchungen, wo Stornieren wie bisher nur die lokale Referenz entfernt. Es braucht keine Salesforce-Verbindung.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 39–41, 46–47; Abschnitt "Sperr-Regel"). Begriffe: "Gebucht", "Stornieren" in `CONTEXT.md`.

**Blocked by:** `.scratch/eintrags-workflow/issues/01` (Gemeinsames Eintrags-Kontextmenü)

**Status:** ready-for-agent

- [ ] Es gibt genau eine zentrale Prüfung "Eintrag ist gebucht"; sie wird in der Service-/Repository-Schicht durchgesetzt, nicht nur in der UI, mit einem eigenen, fangbaren Fehlertyp.
- [ ] Gesperrt sind: Bearbeiten (alle Felder), Löschen einzeln, Löschen gesammelt.
- [ ] Existieren "Verschieben" und die Sammel-Bereinigung aus der Eintrags-Workflow-Spec bereits, hängt dieses Ticket die Sperre an deren vorgesehener Prüfstelle ein (gebuchte Einträge verhindern das Verschieben atomar bzw. sind in der Bereinigung ausgegraut). Existieren sie noch nicht, ist das im Ticket vermerkt und nichts weiter zu tun.
- [ ] Sammelaktionen mit mindestens einem gebuchten Eintrag werden vollständig abgelehnt, mit Grund und Anzahl der gebuchten Einträge; es wird nichts teilweise ausgeführt.
- [ ] Erlaubt bleiben: Flags setzen und entfernen (einzeln und gesammelt), Fortsetzen, Beschreibung kopieren.
- [ ] Im gemeinsamen Kontextmenü sind gesperrte Aktionen bei gebuchten Einträgen deaktiviert; ein Doppelklick öffnet den Eintrags-Dialog schreibgeschützt oder zeigt die Meldung.
- [ ] "Buchung stornieren" ersetzt "Jira-Buchung lokal entfernen…" und erscheint bei jedem gebuchten Eintrag. Für Jira entfernt es nur die lokale Referenz, mit dem bestehenden Hinweis, dass der Worklog in Jira bleibt. Die Operation ist nach Buchungssystem erweiterbar (Ticket 10 ergänzt Salesforce).
- [ ] Nach dem Stornieren ist der Eintrag wieder voll änderbar.
- [ ] Tests auf Service-Ebene: Bearbeiten, Löschen einzeln und gesammelt werden abgelehnt; Flags und Fortsetzen funktionieren; Stornieren (Jira) gibt frei; gemischte Sammelaktion verändert nichts.
