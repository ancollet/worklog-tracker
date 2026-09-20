# 04: Salesforce-Account registrieren

**What to build:** Im Kunden-Tab wähle ich "Salesforce-Account registrieren…" und sehe alle Accounts unserer Org, die mindestens ein offenes Projekt haben. Ich filtere per Namenseingabe, wähle einen Account und habe danach einen Kunden mit Buchungssystem Salesforce, dessen Name und Account-ID übernommen sind. Einen Kunden, den ich früher von Hand angelegt habe, kann ich nachträglich mit seinem Account verbinden, ohne meine Einträge zu verlieren.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 9–13, 20, 23). Begriff: "Registrieren" in `CONTEXT.md`.

**Blocked by:** 01 (Salesforce-Verbindung)

**Status:** ready-for-agent

- [x] Der Salesforce-Client listet Accounts mit mindestens einem offenen Projekt (ID, Name). Objekt-, Feld- und Statusnamen sind bis zur Klärung in Ticket 03 als klar benannte Annahmen an einer Stelle im Client hinterlegt.
- [x] Auswahldialog im Kunden-Tab mit Namensfilter; lädt im Hintergrund, zeigt Ladezustand und Fehler verständlich an.
- [x] Registrieren legt einen Kunden mit Namen des Accounts, Buchungssystem Salesforce und der Account-ID als externer Referenz an.
- [x] Bereits registrierte Accounts sind in der Liste markiert und nicht erneut registrierbar.
- [x] Eine Account-ID kann nur an einem Kunden hängen (leere Werte ausgenommen); das ist auf Datenebene durchgesetzt, inkl. Migration bestehender Datenbanken.
- [x] Ein bestehender Kunde lässt sich über "Verbinden…/Ändern…" mit einem Account verbinden; dabei wird sein Buchungssystem auf Salesforce gesetzt, Projekte und Einträge bleiben erhalten.
- [x] Bei Salesforce-Kunden ist das freie Textfeld für die externe Referenz durch die Anzeige des verbundenen Accounts ersetzt; bei Jira-Kunden und Kunden ohne Buchungssystem bleibt alles wie heute.
- [x] Salesforce-IDs sind nirgends in der UI sichtbar oder einzutippen.
- [x] Ohne Verbindung ist die Funktion deaktiviert bzw. meldet den Fehler; der Kunden-Tab selbst funktioniert offline unverändert.
- [x] Tests: Client-Abfrage mit gefälschtem HTTP (Treffer, leer, Fehler); Registrieren legt den Kunden korrekt an; Doppelregistrierung abgelehnt; nachträgliches Verbinden erhält Projekte und Einträge; Migration.

## Comments

- Umsetzung Ticket 04: Alle Kriterien bis auf "Salesforce-IDs sind nirgends in der UI sichtbar" abgehakt. Für den Account ist es erfüllt und per Offscreen-Smoke-Test geprüft (Baumspalte, Kunden-Details und Auswahldialog zeigen nur Namen; das Freitextfeld wird bei Salesforce-Kunden nie mit der ID gefüllt). Offen bleibt bis Ticket 05 die externe Referenz von *Projekten* eines Salesforce-Kunden (Freitextfeld "Salesforce Projekt-ID" und Baumspalte) — das ist dort ein eigenes Kriterium.
- Org-Namen (`Project__c`, `Account__c`, `Status__c`, offen = `Open`) sind Annahmen, als Konstanten oben in `worklog/services/salesforce.py`; in Ticket 03 gegen die Sandbox zu bestätigen.
- Schema-Schritt "→ 7" (unabhängig von Schritt 6/Snippets): partieller Unique-Index auf der Account-ID von Salesforce-Kunden plus Spalte `customer.external_name` (Name des verbundenen Accounts für die Anzeige). Von Hand doppelt eingetragene Account-IDs: der älteste Kunde behält den Account, die übrigen bleiben mit Projekten und Einträgen erhalten, verlieren aber die ID.
- Die UI ist nicht gegen eine echte Org abgenommen (Ticket 11).
- Nachtrag aus Ticket 05: Auch bei Projekten von Salesforce-Kunden ist die ID jetzt weder sichtbar noch einzutippen (Baumspalte und Details zeigen den Namen des Salesforce-Projekts; die ID kommt nur aus Registrieren/Verbinden). Per Offscreen-Smoke-Test geprüft, Kriterium abgehakt.
