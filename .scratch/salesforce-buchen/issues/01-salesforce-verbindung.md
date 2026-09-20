# 01: Salesforce-Verbindung

**What to build:** In den Einstellungen hinterlege ich Instance-URL, Consumer Key und Consumer Secret der External Client App und klicke "Verbindung testen". Die App meldet sich mit dem gemeinsamen Integrations-User an und zeigt mir eine klare Erfolgs- oder Fehlermeldung. Der bisherige Platzhalter-Abschnitt "Salesforce" ist durch diese echten Einstellungen ersetzt.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 1–3, 7–8; Abschnitt "Anmeldung"). Entscheidung: `docs/adr/0002-salesforce-integrations-user.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] Neuer Salesforce-Client als eigenes Modul; Objekt- und Feldnamen der Org sowie die API-Version leben ausschließlich dort. Seine Schnittstelle spricht in Domänenbegriffen, nicht in SOQL.
- [x] Anmeldung per OAuth Client-Credentials-Flow gegen die Instance-URL; exakter Endpunkt und Parameter sind vor der Umsetzung gegen die aktuelle Salesforce-Dokumentation geprüft (Context7).
- [x] Das Zugriffstoken wird nur im Speicher gehalten; bei einer 401-Antwort wird es genau einmal erneuert und der Aufruf wiederholt.
- [x] HTTP über die Standardbibliothek, keine neue Abhängigkeit (Vorbild: Jira-Client).
- [x] Fehler werden in unterscheidbare, lesbare Fehlertypen abgebildet: Anmeldung abgelehnt, Netz nicht erreichbar, Org-Fehler mit dem Meldungstext von Salesforce.
- [x] Einstellungen: Instance-URL und Consumer Key in der Settings-Tabelle; Consumer Secret im OS-Keyring unter eigenem Schlüssel, nie in der Datenbank. Ist der Keyring nicht erreichbar, erscheint eine verständliche Meldung.
- [x] "Verbindung testen" arbeitet mit den aktuell im Dialog eingegebenen Werten (auch ungespeichert), läuft ohne die UI einzufrieren und zeigt Erfolg bzw. den Fehlertext.
- [x] Der Platzhalter-Abschnitt "Salesforce" ist ersetzt; eine zuvor gespeicherte Instance-URL bleibt erhalten.
- [x] Es gibt eine zentrale Abfrage "Salesforce ist vollständig konfiguriert", die sagt, was fehlt; spätere Tickets nutzen sie zum Deaktivieren ihrer Funktionen.
- [x] Die App startet und trackt ohne Netz und ohne Salesforce-Konfiguration unverändert.
- [x] Tests mit gefälschtem HTTP an der Transportgrenze: Token holen, Wiederholung nach 401 (genau einmal), Anmeldung abgelehnt, Netzfehler, Org-Fehler mit lesbarem Text.

## Comments

Umsetzung (Agent, 2026-09-20):

- Client: `worklog/services/salesforce.py` (`SalesforceClient.test_connection()`, Fehlertypen `SalesforceAuthError`, `SalesforceNetworkError`, `SalesforceOrgError`, Basis `SalesforceError`; `API_VERSION` als Konstante). Objekt-/Feldnamen der Org kommen mit den Folgetickets in dasselbe Modul.
- OAuth-Endpunkt per Context7 (`/llmstxt/developer_salesforce_llms_txt`, developer.salesforce.com) geprüft: `POST {Instance-URL}/services/oauth2/token`, form-encoded `grant_type=client_credentials`, `client_id`, `client_secret`; Antwort mit `access_token`. `scope` wird nicht gesendet (in der Plattform-Doku optional; nur die Marketing-Cloud-Anleitung verlangt ihn).
- Zentrale Abfrage: `worklog/services/salesforce_settings.py` → `load_configuration(conn)` liefert `is_complete`, `missing`, `missing_text`, `credentials`. Die leistende Person (Story 7) ergänzt das Folgeticket in `missing`.
- Verifiziert durch: `tests/test_salesforce_client.py`, `tests/test_salesforce_settings.py`; Offscreen-Smoke-Tests des Settings-Dialogs (ungespeicherte Werte, Hintergrund-Thread, UI-Timer tickt während des Tests, Fehlertexte, Secret nicht in der DB, Keyring-Meldung, Schließen bei laufendem Test) und des App-Starts mit blockiertem Netz (Start, Fenster, Eintrag tracken, null Netzaufrufe).
- Nicht verifiziert: Anmeldung gegen die echte Org bzw. Sandbox (External Client App steht noch nicht bereit), insbesondere ob `GET /services/data/{API_VERSION}/` mit den Rechten des Integrations-Users durchgeht.
