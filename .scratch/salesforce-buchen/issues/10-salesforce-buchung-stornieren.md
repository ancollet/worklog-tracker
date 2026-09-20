# 10: Salesforce-Buchung stornieren

**What to build:** Ich habe einen Eintrag falsch gebucht. Per Rechtsklick wähle ich "Buchung stornieren": Die Kostenposition wird in Salesforce gelöscht und mein Eintrag ist wieder frei zum Ändern und erneuten Buchen. Ist die Kostenposition in Salesforce nicht mehr im Status Open (z.B. schon abgerechnet), wird das Storno mit einer verständlichen Meldung abgelehnt und der Eintrag bleibt gesperrt. Wurde die Kostenposition in Salesforce bereits von Hand gelöscht, wird der Eintrag trotzdem freigegeben.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 42–45). Begriff: "Stornieren" in `CONTEXT.md`.

**Blocked by:** 07 (Gebucht = gesperrt und "Buchung stornieren"), 08 (Einen Eintrag in Salesforce buchen)

**Status:** ready-for-agent

- [x] Der Salesforce-Client löscht eine Kostenposition und unterscheidet drei Ausgänge: gelöscht, nicht gefunden, nicht mehr Open bzw. von der Org abgelehnt (mit dem Meldungstext von Salesforce), plus Netz-/Anmeldefehler.
- [x] Vor dem Löschen wird der Status der Kostenposition geprüft; nur Status Open wird gelöscht. (Ob die Org das Löschen in anderen Status selbst verhindert, klärt Ticket 03; die App verlässt sich nicht darauf.)
- [x] Die Stornieren-Operation aus Ticket 07 ist um das Buchungssystem Salesforce erweitert: gelöscht oder nicht gefunden → Buchungsreferenz, Link, Nummer und Buchungszeitpunkt werden entfernt, der Eintrag ist frei; abgelehnt oder Fehler → der Eintrag bleibt unverändert gesperrt.
- [x] Rückfrage vor dem Storno nennt die Nummer der Kostenposition und dass sie in Salesforce gelöscht wird.
- [x] Bei "nicht gefunden" wird der Nutzer informiert, dass die Kostenposition in Salesforce schon fehlte.
- [x] Die aufgerundete Dauer bleibt nach dem Storno stehen; sie ist danach von Hand änderbar.
- [x] Ein stornierter Eintrag lässt sich erneut buchen und ergibt eine neue Kostenposition.
- [x] "Buchung stornieren" ist in diesem Ticket nur bei genau einem Eintrag aktiv; der Aufruf läuft im Hintergrund.
- [x] Jira-Stornos verhalten sich unverändert wie in Ticket 07.
- [x] Tests mit gefälschtem HTTP: Erfolg gibt frei und entfernt alle Buchungsfelder; nicht mehr Open lehnt ab und lässt den Eintrag gesperrt; nicht gefunden gibt frei; Netzfehler lässt alles unverändert; erneutes Buchen nach Storno funktioniert.

## Umsetzung

- Client: `delete_cost_item(cost_item_id)` in `worklog/services/salesforce.py` (Block "Kostenposition löschen"). Ausgänge: kehrt zurück = gelöscht; `CostItemNotFoundError` (Abfrage findet nichts, DELETE antwortet 404, oder die Referenz ist gar keine Salesforce-ID); `CostItemNotOpenError` (Status vor dem Löschen per Abfrage geprüft, es wird dann kein DELETE gesendet); `CostItemDeleteRefusedError` (die Org lehnt das DELETE mit 4xx ab, mit dem Text von Salesforce); sonst die üblichen Netz-/Anmelde-/Org-Fehler. `SalesforceOrgError` trägt dafür jetzt `http_status`.
- ANNAHMEN, in Ticket 03 zu bestätigen: Der Integrations-User sieht jede Kostenposition (ein für ihn unsichtbarer Datensatz sähe wie "nicht gefunden" aus und würde lokal freigegeben), darf Kostenpositionen im Status Open löschen, und die Statuswerte/-felder stimmen (`COST_ITEM_STATUS_FIELD`, `COST_ITEM_STATUS_OPEN`). Wie die Org das Löschen in anderen Status verhindert, ist offen; deshalb gilt jede 4xx-Antwort auf das DELETE als Ablehnung. REST laut Salesforce-Doku: `DELETE /services/data/vXX.X/sobjects/<Objekt>/<Id>`, Erfolg = 204 ohne Body, Fehler als Liste aus `errorCode`/`message`. Dass ein bereits gelöschter Datensatz 404 (`ENTITY_IS_DELETED`/`NOT_FOUND`) liefert, ist nicht gegen die Sandbox geprüft.
- Storno-Operation (Qt-frei): `worklog/services/booking.py`, drei Phasen wie beim Buchen: `prepare_cancellation` (DB) → `delete_cost_item` (Netz) → `record_cancellation` (DB), zusammen `cancel_booking(conn, log_id, salesforce_client=...)` mit den Ausgängen `CANCELLED` / `CANCELLED_COST_ITEM_MISSING`. Eine Salesforce-Buchung wird ohne Client nie nur lokal entfernt (`CancelRefusedError`). Scheitert nach dem Löschen das lokale Freigeben, heilt ein erneutes Storno das über "nicht gefunden".
- UI: `worklog/ui/salesforce_cancel.py` (Rückfrage, modaler Wartedialog, Aufruf über `start_salesforce_call` im Hintergrund, Meldungen); `cancel_entry_booking` in `worklog/ui/entry_context_menu.py` verzweigt dorthin. Fürs Stornieren genügt die Verbindung (`is_connection_complete`), die leistende Person wird nicht gebraucht.
- Nicht automatisiert geprüft (UI laut Spec ohne Tests): Rückfrage, Hintergrund-Aufruf, Meldungen und Aktualisierung beider Tabs nur per Offscreen-Smoke-Test mit gefälschtem Client. Abnahme gegen die Sandbox (Ticket 11) steht aus.
