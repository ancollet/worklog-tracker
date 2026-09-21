# 03: Sandbox-Recherche zu Org-Feldern und Rechten

**What to build:** Vier Fragen zur Salesforce-Org lassen sich nur mit Zugriff auf die Org beantworten. Sie sollen früh geklärt und hier im Ticket unter "## Answer" dokumentiert werden, damit die übrigen Tickets die echten Namen verwenden können. Braucht die bereitgestellte External Client App und eine Sandbox. Dieses Ticket blockiert nur die Abnahme (11); je früher es erledigt ist, desto weniger muss dort korrigiert werden.

Spec: `.scratch/salesforce-buchen/spec.md` (Abschnitt "Offene Recherchepunkte").

**Blocked by:** 01 (Salesforce-Verbindung), damit die Anmeldung mit der External Client App nachweislich funktioniert

**Status:** ready-for-human

- [x] Pflichtfelder und Automation: Eine Kostenposition wird in der Sandbox nur mit Projekt, Person, Menge, Delivery Date, Beschreibung, Status, Service Type, Skill Level, Location und Count against Budget angelegt. Dokumentiert ist, ob das gelingt, ob Tagessatz und Preis pro Einheit von der Org gesetzt wurden und welche Validierungsregeln oder weiteren Pflichtfelder greifen.
- [x] Projekt: API-Name des Objekts, des Statusfelds und der Wert bzw. die Werte, die "offen" bedeuten; API-Name des Felds, über das das Projekt am Account hängt; API-Name des Anzeigenamens.
- [ ] Löschen: Darf der Integrations-User eine Kostenposition mit Status Open löschen? Was passiert in anderen Status (verhindert die Org das selbst, mit welcher Fehlermeldung)?
- [x] Picklisten: exakte API-Werte für Service Type (Consulting, Development), Skill Level (Standard), Location (Remote) und Status (Open).
- [x] Customer Request Type: bestätigt, dass das Feld Freitext ist, inkl. maximaler Länge; ebenso die maximale Länge der Beschreibung.
- [ ] Rechte des Integrations-Users geprüft: Accounts, Projekte, User lesen; Kostenpositionen anlegen und löschen; nichts darüber hinaus.
- [ ] Alle Antworten stehen unter "## Answer" in dieser Datei, mit einem Beispiel-Request und der Antwort der Org pro Punkt (ohne Secrets).

## Answer

Stand 21.09.2026, geprüft gegen die Sandbox `brightercloud--part` mit dem Client der App (describe, SOQL, ein Anlege-/Lösch-Test). Eingetragen in `worklog/services/salesforce.py` (Commits `e9bee3d`, `83ee2ff`).

**Projekt** — Objekt `Project__c`, Anzeigename `Name`, Status `Status__c` mit den Werten `Planned | In Progress | Done`. Einen Wert "Open" gibt es nicht; als offen gelten laut Entscheidung des Nutzers `Planned` und `In Progress` (36 von 129 Projekten). Ein Feld `Account__c` gibt es nicht, sondern zwei Account-Lookups: `BillingAccount__c` (Pflicht) und `EndCustomer__c` (optional, weicht bei 17 von 129 Projekten ab). Kunde in Worklog = `BillingAccount__c` (Entscheidung des Nutzers). Fehler vor der Korrektur: `No such column 'Account__c' on entity 'Project__c'`.

**Pflichtfelder und Automation** — `POST …/sobjects/ProjectCostItem__c` nur mit Projekt, Person, Menge, Delivery Date, Beschreibung, Status, Service Type, Skill Level, Location, Count against Budget gelingt (`PCI-26-09-33727`). Einziges Pflichtfeld laut describe ist `Project__c`; die Nummer (`Name`) ist eine Auto-Number. `PricePerUnit__c` setzt die Org selbst (87,50 bzw. 143,75 je nach Projekt). Validierungsregel: Bei Projekten mit `CustomerRequestIsMandatorry__c = true` (39 von 129) lehnt die Org ohne Request Type ab: `HTTP 400: Please Enter a Request Type e.g. Lightning, Support, ....` — mit Request Type gelingt es (`PCI-26-09-33728`). Folgeticket: 12.

**Picklisten** (API-Werte, `*` = Default der Org) — Status `*Open | Invoiced | Paid | Aborted | No Payment`; Service Type `Consulting | Development | Travelling`; Skill Level `*Standard | Junior | Senior | Architect`; Location `*Remote | OnSite`. Die Werte im Client stimmen.

**Customer Request Type / Beschreibung** — `CustomerRequestType__c` und `Description__c` sind einzeilige Textfelder, je 255 Zeichen. Die App lehnt längere Texte jetzt vor dem Senden ab (`COST_ITEM_TEXT_MAX_LENGTH`).

**Löschen** — Der Integrations-User darf eine Kostenposition im Status Open löschen (beide Test-Positionen angelegt, gelöscht, per Abfrage als verschwunden bestätigt). Er sieht alle Kostenpositionen (10.382). OFFEN: Ob die Org das Löschen in anderen Status selbst verhindert, wurde nicht ausprobiert, weil dafür ein echter abgerechneter Datensatz gelöscht werden müsste; die App prüft den Status vorher und sendet dann kein DELETE (gegen eine `Invoiced`-Position bestätigt).

**Rechte** — Accounts, Projekte, User lesen sowie Kostenpositionen anlegen/löschen funktioniert. OFFEN / Auffälligkeit: laut describe darf der Integrations-User deutlich mehr als nötig, u.a. `Project__c`, `ExternalProject__c`, `InvoiceCostItem__c` und `TravelCost__c` anlegen und löschen. Das widerspricht "nichts darüber hinaus" und sollte ein Admin am Permission Set einschränken.

