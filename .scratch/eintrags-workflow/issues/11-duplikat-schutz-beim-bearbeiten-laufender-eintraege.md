# 11: Duplikat-Schutz beim Bearbeiten laufender Einträge

**What to build:** Der Schutz gegen doppelt laufende Einträge greift heute nur beim Starten. Bearbeite ich einen laufenden Eintrag so, dass Projekt, Task und Beschreibung mit einem anderen laufenden Eintrag identisch werden, entsteht ungeprüft ein Duplikat. Nach diesem Ticket lehnt auch der Bearbeiten-Pfad das ab und zeigt den Hinweis "läuft bereits"; der Eintrag bleibt unverändert.

Gefunden im Code-Review zu Ticket 02. Entscheidung: `docs/adr/0001-mehrere-laufende-eintraege.md` ("Ein Eintrag mit identischem Projekt, Task und identischer Beschreibung kann nicht zweimal gleichzeitig laufen").

**Blocked by:** None (can start immediately)

**Status:** needs-triage

- [ ] Die Duplikat-Prüfung (Vergleich nach Trimmen; leer und nicht gesetzt gelten als gleich) liegt an einer Stelle im Timer-Service und wird von Starten und Bearbeiten genutzt; der bearbeitete Eintrag selbst zählt nicht als Duplikat.
- [ ] Speichern eines laufenden Eintrags im Eintrags-Dialog lehnt mit dem fangbaren Fehlertyp ab und zeigt "läuft bereits"; der Dialog bleibt offen.
- [ ] Dasselbe gilt für "Aktuellen Eintrag bearbeiten" im Quick-Add-Popup, solange es existiert (entfällt mit Ticket 03).
- [ ] Gestoppte Einträge sind nicht betroffen.
- [ ] Tests auf Service-Ebene mit der In-Memory-DB: Bearbeiten zum Duplikat wird abgelehnt, Bearbeiten ohne Kollision geht durch, unveränderte Felder des Eintrags selbst sind kein Duplikat.
