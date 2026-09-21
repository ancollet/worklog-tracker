# 12: Customer Request Type als Pflicht pro Projekt erkennen

**What to build:** Manche Salesforce-Projekte verlangen auf jeder Kostenposition einen Customer Request Type (Kontrollkästchen "Customer Request is Mandatorry" am Projekt, in der Sandbox 39 von 129 Projekten). Heute erfahre ich das erst, wenn Salesforce die Buchung mit "Please Enter a Request Type e.g. Lightning, Support, ...." ablehnt. Die App soll das vorher wissen: Beim Buchen ist der Request Type für solche Projekte ein Pflichtfeld, eine Buchung ohne ihn wird lokal mit einer deutschen Meldung abgelehnt, und in der Kunden-Ansicht sehe ich am Projekt, dass ein Request Type verlangt wird.

Spec: `.scratch/salesforce-buchen/spec.md`. Begriff: "Customer Request Type" in `CONTEXT.md` (dort um die Pflicht pro Projekt ergänzen). Befund: Ticket 03, "## Answer".

**Blocked by:** —

**Status:** ready-for-agent

- [ ] Der Salesforce-Client liefert pro Salesforce-Projekt, ob der Request Type Pflicht ist (`CustomerRequestIsMandatorry__c`, Schreibweise der Org; der Name steht wie alle Org-Namen nur in `worklog/services/salesforce.py`).
- [ ] Das Projekt speichert die Pflicht lokal (Migration 11, neue Spalte am Projekt, Default "nicht Pflicht").
- [ ] Beim Registrieren eines Projekts wird der Wert übernommen; der Abgleich registrierter Projekte aktualisiert ihn mit (dieselbe Abfrage wie die Offen-Prüfung, kein zusätzlicher Aufruf pro Projekt).
- [ ] Die Prüfung vor dem Buchen lehnt eine Buchung ohne Request Type auf ein Pflicht-Projekt lokal ab (`INVALID_VALUES`), ohne Salesforce zu fragen, mit einer Meldung, die das Projekt nennt.
- [ ] Im Buchungsdialog (Einzel- und Sammelbuchung) ist das Feld bei Pflicht-Projekten als Pflicht gekennzeichnet; eine leere Zeile ist vor dem Absenden als fehlerhaft erkennbar.
- [ ] In der Kunden-Ansicht zeigt das Projekt-Detail beim Feld Customer Request Type den Hinweis "von Salesforce verlangt", wenn er Pflicht ist und leer.
- [ ] Die Ablehnung durch die Org bleibt als zweite Verteidigungslinie unverändert behandelt (Zeilenfehler mit dem Text von Salesforce), falls der lokale Wert veraltet ist.
- [ ] Tests mit gefälschtem HTTP: Registrieren übernimmt den Wert; Abgleich aktualisiert ihn in beide Richtungen; Pflicht + leer wird lokal abgelehnt, ohne Request; Pflicht + gefüllt und nicht Pflicht + leer werden gebucht; Migration auf einer Datenbank im Stand 10.

## Comments
