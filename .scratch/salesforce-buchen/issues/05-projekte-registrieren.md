# 05: Projekte registrieren

**What to build:** Bei einem Salesforce-Kunden wähle ich "Projekte registrieren…" und sehe dessen offene Salesforce-Projekte. Ich hake die an, auf die ich buchen will, lege pro Projekt den Default-Service-Type fest (vorbelegt mit meinem globalen Default aus den Einstellungen) und trage bei Bedarf einen Customer Request Type ein. Danach kann ich auf diese Projekte tracken wie auf jedes andere. Beide Werte kann ich später am Projekt ändern, und ein früher von Hand angelegtes Projekt kann ich nachträglich mit einem Salesforce-Projekt verbinden.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 6, 14–20). Begriffe: "Registrieren", "Service Type", "Customer Request Type" in `CONTEXT.md`.

**Blocked by:** 04 (Salesforce-Account registrieren)

**Status:** ready-for-agent

- [ ] Der Salesforce-Client listet die offenen Projekte eines Accounts (ID, Name).
- [ ] Einstellungen: globaler Default für den Service Type (Consulting oder Development).
- [ ] Neue Felder am Projekt über eine Schema-Migration: Default-Service-Type und Customer Request Type (Freitext, optional).
- [ ] Auswahldialog pro Salesforce-Kunde: offene Projekte mit Mehrfachauswahl; pro gewähltem Projekt Service Type (vorbelegt mit dem globalen Default) und optionaler Customer Request Type.
- [ ] Registrieren legt pro gewähltem Salesforce-Projekt genau ein Projekt unter dem Kunden an, mit Namen und Salesforce-Projekt-ID als externer Referenz.
- [ ] Bereits registrierte Projekte sind in der Liste markiert und nicht erneut registrierbar; eine Salesforce-Projekt-ID kann nur an einem Projekt hängen (leere Werte ausgenommen), auf Datenebene durchgesetzt.
- [ ] Service Type und Customer Request Type sind am registrierten Projekt im Kunden-Tab änderbar.
- [ ] Ein bestehendes Projekt eines Salesforce-Kunden lässt sich über "Verbinden…/Ändern…" mit einem offenen Salesforce-Projekt verbinden; seine Einträge bleiben erhalten.
- [ ] Bei Projekten von Salesforce-Kunden ist das freie Textfeld für die externe Referenz durch die Anzeige des verbundenen Salesforce-Projekts ersetzt; bei anderen Kunden bleibt alles wie heute.
- [ ] Salesforce-IDs sind nirgends sichtbar; der Dialog lädt im Hintergrund und meldet Fehler verständlich.
- [ ] Registrierte Projekte stehen sofort in allen Projektauswahlen (Timer-Tab, Quick-Start, Eintrags-Dialog) zur Verfügung.
- [ ] Tests: Client-Abfrage mit gefälschtem HTTP; Registrieren mehrerer Projekte mit Defaults; Doppelregistrierung abgelehnt; nachträgliches Verbinden erhält Einträge; Ändern von Service Type und Customer Request Type; Migration.
