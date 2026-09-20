# 08: Einen Eintrag in Salesforce buchen

**What to build:** Ich klicke mit rechts auf einen Eintrag eines registrierten Projekts und wähle "In Salesforce buchen…". Ein Buchungsdialog zeigt mir, was in Salesforce landen wird: Datum, Projekt, Menge (auf halbe Stunden aufgerundet), Service Type, Customer Request Type und die Beschreibung als "Task: Beschreibung". Ich kann Menge, Service Type, Request Type und Beschreibung anpassen und bestätige. Die Kostenposition wird im Namen meiner leistenden Person angelegt, die Dauer meines Eintrags wird auf die gebuchte Menge gesetzt, und die Spalte "Gebucht" zeigt die Nummer der Kostenposition mit Link zum Datensatz.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 24–29, 32–33, 36–38; Abschnitte "Mengen- und Textregeln", "Schema"). Begriffe: "Buchung", "Kostenposition" in `CONTEXT.md`.

**Blocked by:** 02 (Leistende Person hinterlegen), 05 (Projekte registrieren), `.scratch/eintrags-workflow/issues/01` (Gemeinsames Eintrags-Kontextmenü)

**Status:** ready-for-agent

- [x] Mengenregel als reine Funktion: Dauer in Stunden, aufgerundet auf das nächste Vielfache von 0,5, mindestens 0,5; exakte halbe oder volle Stunden bleiben unverändert (1 min → 0,5; 30 min → 0,5; 31 min → 1,0; 1h10 → 1,5; 2h → 2,0).
- [x] Beschreibungsregel als reine Funktion: "Task: Beschreibung"; ohne Task nur Beschreibung; ohne Beschreibung nur Task; ohne beides nicht buchbar.
- [x] Ein Buchungs-Service baut aus einem Eintrag einen Buchungsvorschlag (Datum = lokales Kalenderdatum des Starts, Projekt, Menge, Service Type vom Projekt, Customer Request Type vom Projekt, Beschreibung) und führt die bestätigte Buchung aus. Er ist der einzige Ort, der diese Regeln kennt.
- [x] Der Salesforce-Client legt eine Kostenposition an und liefert ID und Nummer zurück. Gesendet werden Projekt, leistende Person, Menge, Delivery Date, Beschreibung, Service Type sowie die festen Werte Status Open, Skill Level Standard, Location Remote, Count against Budget wahr. Customer Request Type nur, wenn nicht leer. Tagessatz, Preis und berechnete Felder werden nie gesendet.
- [x] Nach Erfolg stehen am Eintrag: ID der Kostenposition als Buchungsreferenz, Link zum Datensatz, Buchungszeitpunkt und die Nummer der Kostenposition (neues Feld über eine Schema-Migration).
- [x] Nach Erfolg ist die Dauer des Eintrags gleich der gebuchten Menge und das Ende gleich Start plus Dauer; bei Fehler bleibt der Eintrag unverändert.
- [x] Buchungsdialog: Datum und Projekt nur lesbar; Menge in 0,5er-Schritten (mindestens 0,5), Service Type (Consulting/Development), Customer Request Type und Beschreibung editierbar. Änderungen im Dialog gelten nur für diese Buchung und ändern weder Projekt-Defaults noch die Beschreibung des Eintrags.
- [x] Der Netzaufruf läuft im Hintergrund; der Bestätigen-Button ist währenddessen gesperrt, sodass ein Doppelklick nicht doppelt bucht. Ein bereits gebuchter Eintrag wird vom Service abgelehnt.
- [x] Fehler der Org (z.B. Validierungsregel) erscheinen mit dem Text von Salesforce im Dialog; der Dialog bleibt zur Korrektur offen.
- [x] Menüpunkt "In Salesforce buchen…" im gemeinsamen Kontextmenü, nur bei Einträgen von Salesforce-Kunden; in diesem Ticket nur bei genau einem Eintrag aktiv. Jira-Kunden behalten "In Jira buchen…".
- [x] Der Menüpunkt ist deaktiviert mit erklärendem Tooltip, wenn Salesforce nicht vollständig konfiguriert ist, die leistende Person fehlt, der Eintrag läuft, bereits gebucht ist, weder Task noch Beschreibung hat oder sein Projekt nicht registriert ist.
- [x] Die Spalte "Gebucht" zeigt bei Salesforce-Buchungen die Nummer der Kostenposition; Tooltip bzw. Klick führt zum Datensatz. Ungebuchte Einträge von Salesforce-Kunden zeigen "—" wie heute bei Jira.
- [x] Tests: beide reinen Funktionen mit allen genannten Fällen; Nutzlast der Kostenposition (feste Werte, keine Preisfelder, Request Type nur wenn gesetzt, überschriebene Dialogwerte); Eintrag nach Erfolg (Referenz, Nummer, aufgerundete Dauer und Ende); Eintrag nach Fehler unverändert; bereits gebuchter Eintrag abgelehnt; Migration.

## Umsetzung

- Regeln, Buchungsvorschlag und Buchung: `worklog/services/salesforce_booking.py` (drei Phasen `prepare_booking` → `submit_booking` → `record_booking`, zusammen `book_entry`; jeweils genau ein Eintrag, damit Ticket 09 sie zeilenweise aufruft). Dialog: `worklog/ui/salesforce_booking.py` (bereits als Tabelle mit Statusspalte, nimmt mehrere Einträge).
- Client: `create_cost_item` und `is_project_open` in `worklog/services/salesforce.py`. Objekt-/Feldnamen und Picklist-Werte der Kostenposition sind ANNAHMEN (Konstanten `COST_ITEM_*` ganz oben), in Ticket 03 gegen die Sandbox zu bestätigen. `is_project_open` ist die Minimalprüfung für ein Projekt und soll mit der Mengen-Prüfung aus Ticket 06 zusammengeführt werden.
- Schema-Schritt "→ 10": `log_entry.external_worklog_number` (Nummer der Kostenposition). Version 9 ist für ein paralleles Ticket reserviert.
- Wird die Kostenposition angelegt, aber das Speichern am Eintrag scheitert, geht die Referenz nicht verloren: `BookingNotRecordedError` trägt sie, der Dialog bietet "Speichern wiederholen" und lässt sich währenddessen nicht still schließen.
- Klick zum Datensatz: Strg+Klick auf die Spalte "Gebucht" im Logs-Tab sowie "Buchung im Browser öffnen" im gemeinsamen Kontextmenü (beide Tabs). Der Tooltip zeigt die Nummer, nicht die URL, weil die URL die Salesforce-ID enthält.
- Nicht automatisiert geprüft (UI laut Spec ohne Tests): nur per Offscreen-Smoke-Test mit gefälschtem Client. Das tatsächliche Öffnen des Browsers und die Abnahme gegen die Sandbox (Ticket 11) stehen aus.
- Bis Ticket 10 entfernt "Buchung stornieren" bei Salesforce nur die lokale Referenz; der Bestätigungstext sagt das jetzt ehrlich.
