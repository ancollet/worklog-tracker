# 06: Abgleich geschlossener Projekte

**What to build:** Wird ein registriertes Projekt in Salesforce geschlossen, erfahre ich das in der App: Beim Öffnen des Kunden-Tabs werden meine registrierten Projekte mit Salesforce abgeglichen und geschlossene sichtbar markiert. Ich kann weiter darauf tracken; nichts wird automatisch archiviert. Ohne Netz bekomme ich nur einen dezenten Hinweis.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 21–23).

**Blocked by:** 05 (Projekte registrieren)

**Status:** ready-for-agent

- [ ] Der Salesforce-Client beantwortet für eine Menge von Salesforce-Projekt-IDs in einem Aufruf, welche davon noch offen sind; nicht mehr vorhandene Projekte gelten als geschlossen.
- [ ] Neue Felder am Projekt über eine Schema-Migration: Kennzeichen "in Salesforce geschlossen" und Zeitpunkt des letzten Abgleichs.
- [ ] Eine Service-Operation "registrierte Projekte abgleichen" aktualisiert Kennzeichen und Zeitpunkt für alle registrierten Projekte und ist von der UI unabhängig aufrufbar (Ticket 09 nutzt sie vor dem Buchen).
- [ ] Der Abgleich läuft beim Öffnen des Kunden-Tabs im Hintergrund, ohne die UI zu blockieren, und nicht häufiger als nötig (kein Aufruf pro Tab-Wechsel im Sekundentakt).
- [ ] Geschlossene Projekte sind im Kunden-Tab sichtbar markiert, mit Tooltip inkl. Zeitpunkt des letzten Abgleichs.
- [ ] Wird ein Projekt in Salesforce wieder geöffnet, verschwindet die Markierung beim nächsten Abgleich.
- [ ] Tracken auf geschlossene Projekte bleibt möglich; kein automatisches Archivieren.
- [ ] Ohne Netz oder Konfiguration: kein Dialog, nur ein dezenter Hinweis; der letzte bekannte Stand bleibt stehen.
- [ ] Tests mit gefälschtem HTTP: offen bleibt offen, geschlossen wird markiert, gelöscht wird markiert, wieder geöffnet wird entmarkiert, Fehler lässt den Stand unverändert; Migration.
