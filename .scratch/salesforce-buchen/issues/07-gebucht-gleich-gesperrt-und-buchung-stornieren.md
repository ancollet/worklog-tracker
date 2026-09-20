# 07: Gebucht = gesperrt und "Buchung stornieren"

**What to build:** Sobald ein Eintrag gebucht ist, kann ich ihn nicht mehr bearbeiten, löschen, verschieben oder bereinigen; ich bekomme die klare Meldung "Eintrag ist gebucht, erst Buchung stornieren". Flags setzen (z.B. "abgerechnet"), Fortsetzen und Beschreibung kopieren gehen weiterhin. Über "Buchung stornieren" im Kontextmenü gebe ich den Eintrag wieder frei. Das gilt einheitlich für alle Buchungssysteme; dieses Ticket liefert es für die bestehenden Jira-Buchungen, wo Stornieren wie bisher nur die lokale Referenz entfernt. Es braucht keine Salesforce-Verbindung.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 39–41, 46–47; Abschnitt "Sperr-Regel"). Begriffe: "Gebucht", "Stornieren" in `CONTEXT.md`.

**Blocked by:** `.scratch/eintrags-workflow/issues/01` (Gemeinsames Eintrags-Kontextmenü)

**Status:** ready-for-agent

- [x] Es gibt genau eine zentrale Prüfung "Eintrag ist gebucht"; sie wird in der Service-/Repository-Schicht durchgesetzt, nicht nur in der UI, mit einem eigenen, fangbaren Fehlertyp.
- [x] Gesperrt sind: Bearbeiten (alle Felder), Löschen einzeln, Löschen gesammelt.
- [x] Existieren "Verschieben" und die Sammel-Bereinigung aus der Eintrags-Workflow-Spec bereits, hängt dieses Ticket die Sperre an deren vorgesehener Prüfstelle ein (gebuchte Einträge verhindern das Verschieben atomar bzw. sind in der Bereinigung ausgegraut). Existieren sie noch nicht, ist das im Ticket vermerkt und nichts weiter zu tun.
- [x] Sammelaktionen mit mindestens einem gebuchten Eintrag werden vollständig abgelehnt, mit Grund und Anzahl der gebuchten Einträge; es wird nichts teilweise ausgeführt.
- [x] Erlaubt bleiben: Flags setzen und entfernen (einzeln und gesammelt), Fortsetzen, Beschreibung kopieren.
- [x] Im gemeinsamen Kontextmenü sind gesperrte Aktionen bei gebuchten Einträgen deaktiviert; ein Doppelklick öffnet den Eintrags-Dialog schreibgeschützt oder zeigt die Meldung.
- [x] "Buchung stornieren" ersetzt "Jira-Buchung lokal entfernen…" und erscheint bei jedem gebuchten Eintrag. Für Jira entfernt es nur die lokale Referenz, mit dem bestehenden Hinweis, dass der Worklog in Jira bleibt. Die Operation ist nach Buchungssystem erweiterbar (Ticket 10 ergänzt Salesforce).
- [x] Nach dem Stornieren ist der Eintrag wieder voll änderbar.
- [x] Tests auf Service-Ebene: Bearbeiten, Löschen einzeln und gesammelt werden abgelehnt; Flags und Fortsetzen funktionieren; Stornieren (Jira) gibt frei; gemischte Sammelaktion verändert nichts.

**Umsetzung:**

- Zentrale Prüfung: `LogEntry.is_booked` (`worklog/models.py`); durchgesetzt in `worklog/repository.py` über `ensure_not_booked(conn, log_ids)` (wirft `EntryBookedError` mit `log_ids`, `count`, `total`) in `update_log`, `delete_log`, `delete_logs_bulk`. `booked_log_ids(conn, log_ids)` liefert die gebuchten Einträge einer Auswahl. Nicht geprüft werden `set_log_external_ref` (Buchen/Stornieren) und die Flag-Funktionen.
- Verschieben existiert: `worklog/services/move.py` (`_check_movable`) fragt jetzt `repo.ensure_not_booked`; der dortige eigene `EntryBookedError` ist im zentralen Fehlertyp aufgegangen.
- Die Sammel-Bereinigung (Eintrags-Workflow Ticket 10) existiert noch nicht. Sie muss gebuchte Einträge über `LogEntry.is_booked` ausgrauen und vor dem Schreiben `repo.ensure_not_booked` fragen (schreibt sie über `repo.update_log`, greift die Sperre ohnehin).
- Stornieren: `worklog/services/booking.py` (`cancel_booking`, `cancel_booking_hint`); Ticket 10 dieser Spec ergänzt dort den Salesforce-Zweig anhand von `log.customer_booking_system`.
- Doppelklick (beide Tabs) öffnet den Eintrags-Dialog schreibgeschützt; gelöst im `LogDialog` selbst.

**Hinweis zur Abnahme:** UI offscreen geprüft (Menü bei gebuchtem Eintrag und gemischter Auswahl, Meldungen bei Löschen/Verschieben, schreibgeschützter Dialog inkl. deaktiviertem Snippet- und Bereinigen-Button, Buttons im Logs-Tab, Stornieren gibt frei). Nicht geprüft: echte Mausbedienung am Bildschirm.
