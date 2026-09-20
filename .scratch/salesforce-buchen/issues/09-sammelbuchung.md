# 09: Sammelbuchung

**What to build:** Ich markiere die Einträge einer Woche, klicke mit rechts und wähle "In Salesforce buchen…". Derselbe Buchungsdialog zeigt jetzt eine Zeile pro Eintrag, jede einzeln anpassbar. Einträge, die nicht buchbar sind, sind ausgegraut, mit Grund. Nach dem Bestätigen sehe ich pro Zeile Erfolg oder den Fehlertext; ein Fehler in einer Zeile bricht die anderen nicht ab, und fehlgeschlagene Zeilen kann ich gleich korrigieren und erneut buchen.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 24, 30–31, 34–35, 38).

**Blocked by:** 06 (Abgleich geschlossener Projekte), 08 (Einen Eintrag in Salesforce buchen)

**Status:** ready-for-agent

- [ ] "In Salesforce buchen…" ist bei Mehrfachauswahl aktiv, wenn mindestens ein Eintrag eines Salesforce-Kunden gewählt ist; bei gemischter Auswahl aus Jira- und Salesforce-Kunden ist Buchen deaktiviert, mit Tooltip.
- [ ] Der Buchungs-Service liefert für eine Liste von Einträgen Buchungsvorschläge inkl. Buchbarkeit und Grund: bereits gebucht, läuft noch, weder Task noch Beschreibung, Projekt nicht registriert, Projekt in Salesforce geschlossen.
- [ ] Vor dem Anzeigen bzw. spätestens vor dem Buchen werden die betroffenen Projekte über die Abgleich-Operation aus Ticket 06 geprüft; schlägt der Abgleich fehl, wird nicht gebucht und der Fehler gemeldet.
- [ ] Der Dialog zeigt eine Zeile pro Eintrag, sortiert nach Datum; nicht buchbare Zeilen sind ausgegraut und nicht editierbar, mit sichtbarem Grund; eine Fußzeile nennt Anzahl und Stundensumme der buchbaren Zeilen.
- [ ] Einzelne buchbare Zeilen lassen sich abwählen.
- [ ] Gebucht wird Zeile für Zeile im Hintergrund mit sichtbarem Fortschritt; jede erfolgreiche Zeile wird sofort lokal festgeschrieben (Referenz, Nummer, aufgerundete Dauer), sodass ein Abbruch keine gebuchten, aber lokal ungebuchten Einträge hinterlässt.
- [ ] Ein Fehler in einer Zeile zeigt den Fehlertext in der Zeile und bricht die übrigen nicht ab; ein Anmelde- oder Netzfehler bricht den Lauf mit einer Meldung ab, statt ihn pro Zeile zu wiederholen.
- [ ] Erfolgreiche Zeilen sind danach gesperrt und als gebucht markiert; fehlgeschlagene bleiben editierbar, und "Erneut buchen" sendet nur diese.
- [ ] Doppeltes Absenden bucht keinen Eintrag zweimal.
- [ ] Nach dem Schließen sind Baum, Logs-Tab und Summen aktuell (Dauern können sich durch das Aufrunden geändert haben).
- [ ] Tests mit gefälschtem HTTP: jeder Nicht-buchbar-Grund; Teilerfolg (mittlere Zeile scheitert); erneutes Buchen nur der fehlgeschlagenen; Abbruch bei Anmeldefehler ohne weitere Aufrufe; geschlossenes Projekt verhindert die Buchung; kein Doppelbuchen.
