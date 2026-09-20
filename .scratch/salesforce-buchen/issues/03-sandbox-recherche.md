# 03: Sandbox-Recherche zu Org-Feldern und Rechten

**What to build:** Vier Fragen zur Salesforce-Org lassen sich nur mit Zugriff auf die Org beantworten. Sie sollen früh geklärt und hier im Ticket unter "## Answer" dokumentiert werden, damit die übrigen Tickets die echten Namen verwenden können. Braucht die bereitgestellte External Client App und eine Sandbox. Dieses Ticket blockiert nur die Abnahme (11); je früher es erledigt ist, desto weniger muss dort korrigiert werden.

Spec: `.scratch/salesforce-buchen/spec.md` (Abschnitt "Offene Recherchepunkte").

**Blocked by:** 01 (Salesforce-Verbindung), damit die Anmeldung mit der External Client App nachweislich funktioniert

**Status:** ready-for-human

- [ ] Pflichtfelder und Automation: Eine Kostenposition wird in der Sandbox nur mit Projekt, Person, Menge, Delivery Date, Beschreibung, Status, Service Type, Skill Level, Location und Count against Budget angelegt. Dokumentiert ist, ob das gelingt, ob Tagessatz und Preis pro Einheit von der Org gesetzt wurden und welche Validierungsregeln oder weiteren Pflichtfelder greifen.
- [ ] Projekt: API-Name des Objekts, des Statusfelds und der Wert bzw. die Werte, die "offen" bedeuten; API-Name des Felds, über das das Projekt am Account hängt; API-Name des Anzeigenamens.
- [ ] Löschen: Darf der Integrations-User eine Kostenposition mit Status Open löschen? Was passiert in anderen Status (verhindert die Org das selbst, mit welcher Fehlermeldung)?
- [ ] Picklisten: exakte API-Werte für Service Type (Consulting, Development), Skill Level (Standard), Location (Remote) und Status (Open).
- [ ] Customer Request Type: bestätigt, dass das Feld Freitext ist, inkl. maximaler Länge; ebenso die maximale Länge der Beschreibung.
- [ ] Rechte des Integrations-Users geprüft: Accounts, Projekte, User lesen; Kostenpositionen anlegen und löschen; nichts darüber hinaus.
- [ ] Alle Antworten stehen unter "## Answer" in dieser Datei, mit einem Beispiel-Request und der Antwort der Org pro Punkt (ohne Secrets).
