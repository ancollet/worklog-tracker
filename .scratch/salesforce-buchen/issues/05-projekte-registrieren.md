# 05: Projekte registrieren

**What to build:** Bei einem Salesforce-Kunden wähle ich "Projekte registrieren…" und sehe dessen offene Salesforce-Projekte. Ich hake die an, auf die ich buchen will, lege pro Projekt den Default-Service-Type fest (vorbelegt mit meinem globalen Default aus den Einstellungen) und trage bei Bedarf einen Customer Request Type ein. Danach kann ich auf diese Projekte tracken wie auf jedes andere. Beide Werte kann ich später am Projekt ändern, und ein früher von Hand angelegtes Projekt kann ich nachträglich mit einem Salesforce-Projekt verbinden.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 6, 14–20). Begriffe: "Registrieren", "Service Type", "Customer Request Type" in `CONTEXT.md`.

**Blocked by:** 04 (Salesforce-Account registrieren)

**Status:** ready-for-agent

- [x] Der Salesforce-Client listet die offenen Projekte eines Accounts (ID, Name).
- [x] Einstellungen: globaler Default für den Service Type (Consulting oder Development).
- [x] Neue Felder am Projekt über eine Schema-Migration: Default-Service-Type und Customer Request Type (Freitext, optional).
- [x] Auswahldialog pro Salesforce-Kunde: offene Projekte mit Mehrfachauswahl; pro gewähltem Projekt Service Type (vorbelegt mit dem globalen Default) und optionaler Customer Request Type.
- [x] Registrieren legt pro gewähltem Salesforce-Projekt genau ein Projekt unter dem Kunden an, mit Namen und Salesforce-Projekt-ID als externer Referenz.
- [x] Bereits registrierte Projekte sind in der Liste markiert und nicht erneut registrierbar; eine Salesforce-Projekt-ID kann nur an einem Projekt hängen (leere Werte ausgenommen), auf Datenebene durchgesetzt.
- [x] Service Type und Customer Request Type sind am registrierten Projekt im Kunden-Tab änderbar.
- [x] Ein bestehendes Projekt eines Salesforce-Kunden lässt sich über "Verbinden…/Ändern…" mit einem offenen Salesforce-Projekt verbinden; seine Einträge bleiben erhalten.
- [x] Bei Projekten von Salesforce-Kunden ist das freie Textfeld für die externe Referenz durch die Anzeige des verbundenen Salesforce-Projekts ersetzt; bei anderen Kunden bleibt alles wie heute.
- [x] Salesforce-IDs sind nirgends sichtbar; der Dialog lädt im Hintergrund und meldet Fehler verständlich.
- [x] Registrierte Projekte stehen sofort in allen Projektauswahlen (Timer-Tab, Quick-Start, Eintrags-Dialog) zur Verfügung.
- [x] Tests: Client-Abfrage mit gefälschtem HTTP; Registrieren mehrerer Projekte mit Defaults; Doppelregistrierung abgelehnt; nachträgliches Verbinden erhält Einträge; Ändern von Service Type und Customer Request Type; Migration.

## Comments

- Umsetzung Ticket 05: Alle Kriterien bis auf "Einstellungen: globaler Default für den Service Type" abgehakt. Dafür steht die Service-Schicht (`load_default_service_type` / `save_default_service_type` in `worklog/services/salesforce_settings.py`, Schlüssel `salesforce.default_service_type`, Default "Consulting", getestet) und alle Vorbelegungen nutzen sie bereits; es fehlt nur das Auswahlfeld im Abschnitt "Salesforce" des Einstellungsdialogs. `worklog/ui/settings_dialog.py` wurde wegen paralleler Arbeit daran bewusst nicht angefasst.
- Org-Namen bleiben Annahmen (Ticket 03): zusätzlich zu Ticket 04 jetzt `PROJECT_NAME_FIELD = "Name"` als Anzeigename des Salesforce-Projekts, oben in `worklog/services/salesforce.py`.
- Schema-Schritt "→ 8": Spalten `project.default_service_type`, `project.customer_request_type`, `project.external_name` (Name des verbundenen Salesforce-Projekts für die Anzeige). Eindeutigkeit der Salesforce-Projekt-ID gilt nur für Projekte von Salesforce-Kunden und ist über Trigger durchgesetzt, weil das Buchungssystem am Kunden hängt und ein partieller Index es nicht sehen kann; bei anderen Kunden bleibt die externe Referenz freier, wiederholbarer Text. Von Hand doppelt eingetragene IDs: das älteste Projekt behält sie, die übrigen bleiben mit Einträgen erhalten. Wird ein Kunde erst später Salesforce-Kunde, verlieren seine Projekte nur bereits vergebene Referenzen.
- Der Auswahldialog aus Ticket 04 ist verallgemeinert (`worklog/ui/salesforce_choice_dialog.py`): Einzelauswahl für Account registrieren/Verbinden und Projekt verbinden, Mehrfachauswahl mit Service Type und Customer Request Type pro Zeile für "Projekte registrieren…".
- Registrieren mehrerer Projekte ist alles-oder-nichts. Hat der Kunde schon ein gleichnamiges, von Hand angelegtes Projekt, wird abgelehnt mit Verweis auf "Verbinden…".
- UI per Offscreen-Smoke-Test mit gefälschtem Client geprüft (Aufrufe nicht im UI-Thread, keine IDs in Baum, Details und Dialog, deaktiviert mit Hinweis ohne Verbindung, Ladefehler lesbar); nicht gegen eine echte Org abgenommen (Ticket 11).
- Nachtrag: Auswahlfeld "Default Service Type" im Salesforce-Abschnitt des Einstellungsdialogs ergänzt (offscreen geprüft: Vorbelegung, Speichern, Wiederöffnen).
