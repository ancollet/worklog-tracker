# 09: Sammelbuchung

**What to build:** Ich markiere die Einträge einer Woche, klicke mit rechts und wähle "In Salesforce buchen…". Derselbe Buchungsdialog zeigt jetzt eine Zeile pro Eintrag, jede einzeln anpassbar. Einträge, die nicht buchbar sind, sind ausgegraut, mit Grund. Nach dem Bestätigen sehe ich pro Zeile Erfolg oder den Fehlertext; ein Fehler in einer Zeile bricht die anderen nicht ab, und fehlgeschlagene Zeilen kann ich gleich korrigieren und erneut buchen.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 24, 30–31, 34–35, 38).

**Blocked by:** 06 (Abgleich geschlossener Projekte), 08 (Einen Eintrag in Salesforce buchen)

**Status:** ready-for-agent

- [x] "In Salesforce buchen…" ist bei Mehrfachauswahl aktiv, wenn mindestens ein Eintrag eines Salesforce-Kunden gewählt ist; bei gemischter Auswahl aus Jira- und Salesforce-Kunden ist Buchen deaktiviert, mit Tooltip.
- [x] Der Buchungs-Service liefert für eine Liste von Einträgen Buchungsvorschläge inkl. Buchbarkeit und Grund: bereits gebucht, läuft noch, weder Task noch Beschreibung, Projekt nicht registriert, Projekt in Salesforce geschlossen.
- [x] Vor dem Anzeigen bzw. spätestens vor dem Buchen werden die betroffenen Projekte über die Abgleich-Operation aus Ticket 06 geprüft; schlägt der Abgleich fehl, wird nicht gebucht und der Fehler gemeldet.
- [x] Der Dialog zeigt eine Zeile pro Eintrag, sortiert nach Datum; nicht buchbare Zeilen sind ausgegraut und nicht editierbar, mit sichtbarem Grund; eine Fußzeile nennt Anzahl und Stundensumme der buchbaren Zeilen.
- [x] Einzelne buchbare Zeilen lassen sich abwählen.
- [x] Gebucht wird Zeile für Zeile im Hintergrund mit sichtbarem Fortschritt; jede erfolgreiche Zeile wird sofort lokal festgeschrieben (Referenz, Nummer, aufgerundete Dauer), sodass ein Abbruch keine gebuchten, aber lokal ungebuchten Einträge hinterlässt.
- [x] Ein Fehler in einer Zeile zeigt den Fehlertext in der Zeile und bricht die übrigen nicht ab; ein Anmelde- oder Netzfehler bricht den Lauf mit einer Meldung ab, statt ihn pro Zeile zu wiederholen.
- [x] Erfolgreiche Zeilen sind danach gesperrt und als gebucht markiert; fehlgeschlagene bleiben editierbar, und "Erneut buchen" sendet nur diese.
- [x] Doppeltes Absenden bucht keinen Eintrag zweimal.
- [x] Nach dem Schließen sind Baum, Logs-Tab und Summen aktuell (Dauern können sich durch das Aufrunden geändert haben).
- [x] Tests mit gefälschtem HTTP: jeder Nicht-buchbar-Grund; Teilerfolg (mittlere Zeile scheitert); erneutes Buchen nur der fehlgeschlagenen; Abbruch bei Anmeldefehler ohne weitere Aufrufe; geschlossenes Projekt verhindert die Buchung; kein Doppelbuchen.

## Umsetzung

- Ablauf des Sammellaufs Qt-frei in `worklog/services/salesforce_booking_run.py` (`BookingRun`): Zeilen nach Datum, Zustand pro Zeile (`OPEN`, `BLOCKED`, `FAILED`, `NOT_RUN`, `UNSAVED`, `BOOKED`), Abgleich in zwei Hälften (`projects_to_check` / `record_check`, blockierend `check_projects`), Lauf als `start` → `next_submission` (DB) → `submit` (nur Netz) → `finish_submission` (DB), blockierend `book`; `stop`, `progress`, `aborted_reason`, `has_unsaved`. Die Regeln einer Buchung bleiben in `salesforce_booking.py`; neu dort nur der Schalter `closed_known` (Kennzeichen "in Salesforce geschlossen" zählt nur direkt nach einem Abgleich; `submit_booking` fragt dann nicht noch einmal pro Zeile).
- Abgleich: der Dialog fragt beim Öffnen EINMAL für alle betroffenen Projekte (`check_open_projects` im Hintergrund, `record_open_projects_check` im UI-Thread). Ohne Antwort ist `BookingRun.start` gesperrt; der Dialog meldet den Fehler und bietet "Erneut prüfen". "Erneut buchen" im selben Dialog fragt nicht erneut.
- Abbruchregel: `SalesforceAuthError` und `SalesforceNetworkError` betreffen alle Zeilen → Lauf endet, übrige Zeilen "Nicht ausgeführt." (bleiben offen für "Erneut buchen"). Alle anderen Fehler bleiben in ihrer Zeile.
- Nie doppelt: gebuchte Zeilen kommen nie wieder in die Warteschlange, egal was bestätigt wird; ein zweites `start` während des Laufs wird abgelehnt; eine angelegte, aber lokal nicht gespeicherte Kostenposition (`UNSAVED`) wird nur noch gespeichert, nie neu angelegt. "Abbrechen"/Schließen während des Laufs hält nach der Zeile an, die gerade unterwegs ist (sie wird noch festgeschrieben).
- Menü (`plan_entry_menu`): bei mehreren Einträgen aktiv, sobald ein Salesforce-Kunde dabei ist; Jira + Salesforce gemischt → deaktiviert mit Tooltip. Zusätzlich zur Ticket-Formulierung: ist KEIN Eintrag der Auswahl buchbar, ist der Punkt deaktiviert mit Grund (z.B. fehlende Einrichtung), statt einen Dialog ohne buchbare Zeile zu öffnen. Einträge von Kunden ohne Buchungssystem in der Auswahl erscheinen im Dialog ausgegraut.
- Dialog: Abwähl-Spalte (nur bei mehreren Zeilen), Fußzeile "n Einträge zu buchen · x,y h", Fortschrittsbalken, ein Client (eine Anmeldung) für den ganzen Dialog. Eine Sammelbuchung bleibt nach vollem Erfolg offen (Nummern pro Zeile sichtbar); ein einzelner Eintrag schließt wie in Ticket 08.
- Nicht automatisiert geprüft (UI laut Spec ohne Tests): nur per Offscreen-Smoke-Test mit gefälschtem Client. Offen bleibt der Fall "Netz bricht WÄHREND des Anlegens ab": dann ist unbekannt, ob die Kostenposition entstanden ist; die Zeile gilt als fehlgeschlagen und könnte beim erneuten Buchen doppelt entstehen — in Salesforce prüfen (Abnahme Ticket 11).
