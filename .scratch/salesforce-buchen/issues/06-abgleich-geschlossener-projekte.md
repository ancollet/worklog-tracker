# 06: Abgleich geschlossener Projekte

**What to build:** Wird ein registriertes Projekt in Salesforce geschlossen, erfahre ich das in der App: Beim Öffnen des Kunden-Tabs werden meine registrierten Projekte mit Salesforce abgeglichen und geschlossene sichtbar markiert. Ich kann weiter darauf tracken; nichts wird automatisch archiviert. Ohne Netz bekomme ich nur einen dezenten Hinweis.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 21–23).

**Blocked by:** 05 (Projekte registrieren)

**Status:** ready-for-agent

- [x] Der Salesforce-Client beantwortet für eine Menge von Salesforce-Projekt-IDs in einem Aufruf, welche davon noch offen sind; nicht mehr vorhandene Projekte gelten als geschlossen.
- [x] Neue Felder am Projekt über eine Schema-Migration: Kennzeichen "in Salesforce geschlossen" und Zeitpunkt des letzten Abgleichs.
- [x] Eine Service-Operation "registrierte Projekte abgleichen" aktualisiert Kennzeichen und Zeitpunkt für alle registrierten Projekte und ist von der UI unabhängig aufrufbar (Ticket 09 nutzt sie vor dem Buchen).
- [x] Der Abgleich läuft beim Öffnen des Kunden-Tabs im Hintergrund, ohne die UI zu blockieren, und nicht häufiger als nötig (kein Aufruf pro Tab-Wechsel im Sekundentakt).
- [x] Geschlossene Projekte sind im Kunden-Tab sichtbar markiert, mit Tooltip inkl. Zeitpunkt des letzten Abgleichs.
- [x] Wird ein Projekt in Salesforce wieder geöffnet, verschwindet die Markierung beim nächsten Abgleich.
- [x] Tracken auf geschlossene Projekte bleibt möglich; kein automatisches Archivieren.
- [x] Ohne Netz oder Konfiguration: kein Dialog, nur ein dezenter Hinweis; der letzte bekannte Stand bleibt stehen.
- [x] Tests mit gefälschtem HTTP: offen bleibt offen, geschlossen wird markiert, gelöscht wird markiert, wieder geöffnet wird entmarkiert, Fehler lässt den Stand unverändert; Migration.

## Comments

- Umsetzung Ticket 06: alle Kriterien abgehakt. Client: `SalesforceClient.open_projects_among(ids) -> set[str]` liefert die noch offenen unter den übergebenen Salesforce-Projekten (in der Schreibweise des Aufrufers; 15- und 18-stellige IDs gelten als gleich). Geschlossene, gelöschte und Referenzen, die gar keine Salesforce-ID sind, fehlen in der Antwort. Viele IDs werden in Blöcken zu 200 abgefragt (die Abfrage reist in der URL eines GET); ein Fehler in irgendeinem Block lässt die ganze Prüfung scheitern, damit nie versehentlich "geschlossen" gemeldet wird. Org-Namen bleiben die Annahmen aus Ticket 03.
- Schema-Schritt "→ 9": `project.salesforce_closed` (Kennzeichen) und `project.salesforce_checked_at` (Zeitpunkt des letzten Abgleichs, leer = nie geprüft). Die Migration markiert selbst nichts.
- Service `worklog/services/salesforce_reconciliation.py` (Qt-frei): `reconcile_registered_projects(conn, client, *, project_ids=None, at=None)` für alle oder nur bestimmte Projekte (Ticket 09: die Projekte der zu buchenden Einträge); dazu die zwei Hälften `check_open_projects(client, ids)` (nur Netz, thread-tauglich) und `record_open_projects_check(conn, check)` (nur Datenbank), weil die SQLite-Verbindung den UI-Thread nicht verlassen darf. `is_closed_in_salesforce(project)` ist die Frage für den Nicht-buchbar-Grund "Projekt in Salesforce geschlossen". Bei Netz-/Anmelde-/Org-Fehlern wird nichts geschrieben.
- Abgeglichen werden Projekte von Salesforce-Kunden mit Salesforce-Projekt, auch archivierte; alle anderen werden weder abgefragt noch angefasst. Wird ein Projekt mit einem anderen Salesforce-Projekt verbunden, verfällt der alte Stand (Kennzeichen und Zeitpunkt).
- Kunden-Tab: Abgleich beim Öffnen des Tabs im Hintergrund, höchstens alle 10 Minuten (auch nach Fehlversuchen) und nie zwei gleichzeitig; kein Netzaufruf beim App-Start (der Kunden-Tab ist nicht der erste Tab). Geschlossene Projekte: Zusatz "– in Salesforce geschlossen" (kursiv) im Baum und in den Projekt-Details, Tooltip mit Zeitpunkt des letzten Abgleichs. Das Ergebnis wird in den bestehenden Baum eingetragen, Auswahl und halb bearbeitete Details bleiben erhalten. Ohne Netz/Konfiguration nur eine graue Hinweiszeile unter dem Baum, inkl. "Angezeigt wird der Stand vom …"; ohne registrierte Projekte gar kein Hinweis.
- UI per Offscreen-Smoke-Test mit gefälschtem Client geprüft (Aufruf nicht im UI-Thread, kein zweiter Aufruf beim sofortigen Tab-Wechsel, markieren/entmarkieren, Fehler und fehlende Konfiguration ohne Dialog, keine IDs); nicht gegen eine echte Org abgenommen (Ticket 11).
