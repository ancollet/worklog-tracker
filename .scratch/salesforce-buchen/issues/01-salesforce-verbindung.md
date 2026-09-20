# 01: Salesforce-Verbindung

**What to build:** In den Einstellungen hinterlege ich Instance-URL, Consumer Key und Consumer Secret der External Client App und klicke "Verbindung testen". Die App meldet sich mit dem gemeinsamen Integrations-User an und zeigt mir eine klare Erfolgs- oder Fehlermeldung. Der bisherige Platzhalter-Abschnitt "Salesforce" ist durch diese echten Einstellungen ersetzt.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 1–3, 7–8; Abschnitt "Anmeldung"). Entscheidung: `docs/adr/0002-salesforce-integrations-user.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Neuer Salesforce-Client als eigenes Modul; Objekt- und Feldnamen der Org sowie die API-Version leben ausschließlich dort. Seine Schnittstelle spricht in Domänenbegriffen, nicht in SOQL.
- [ ] Anmeldung per OAuth Client-Credentials-Flow gegen die Instance-URL; exakter Endpunkt und Parameter sind vor der Umsetzung gegen die aktuelle Salesforce-Dokumentation geprüft (Context7).
- [ ] Das Zugriffstoken wird nur im Speicher gehalten; bei einer 401-Antwort wird es genau einmal erneuert und der Aufruf wiederholt.
- [ ] HTTP über die Standardbibliothek, keine neue Abhängigkeit (Vorbild: Jira-Client).
- [ ] Fehler werden in unterscheidbare, lesbare Fehlertypen abgebildet: Anmeldung abgelehnt, Netz nicht erreichbar, Org-Fehler mit dem Meldungstext von Salesforce.
- [ ] Einstellungen: Instance-URL und Consumer Key in der Settings-Tabelle; Consumer Secret im OS-Keyring unter eigenem Schlüssel, nie in der Datenbank. Ist der Keyring nicht erreichbar, erscheint eine verständliche Meldung.
- [ ] "Verbindung testen" arbeitet mit den aktuell im Dialog eingegebenen Werten (auch ungespeichert), läuft ohne die UI einzufrieren und zeigt Erfolg bzw. den Fehlertext.
- [ ] Der Platzhalter-Abschnitt "Salesforce" ist ersetzt; eine zuvor gespeicherte Instance-URL bleibt erhalten.
- [ ] Es gibt eine zentrale Abfrage "Salesforce ist vollständig konfiguriert", die sagt, was fehlt; spätere Tickets nutzen sie zum Deaktivieren ihrer Funktionen.
- [ ] Die App startet und trackt ohne Netz und ohne Salesforce-Konfiguration unverändert.
- [ ] Tests mit gefälschtem HTTP an der Transportgrenze: Token holen, Wiederholung nach 401 (genau einmal), Anmeldung abgelehnt, Netzfehler, Org-Fehler mit lesbarem Text.
