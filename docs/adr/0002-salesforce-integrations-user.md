---
status: accepted
---

# Salesforce-Anmeldung über einen gemeinsamen Integrations-User

Die App meldet sich über die External Client App mit einem gemeinsamen technischen User an (Client-Credentials), nicht mit dem persönlichen Salesforce-Login des Nutzers. Die leistende Person (`Person__c`) hinterlegt jeder Nutzer einmalig in den Einstellungen. So braucht niemand einen interaktiven OAuth-Login, und die Rechte zum Anlegen von Kostenpositionen werden an genau einer Stelle gepflegt.

## Considered Options

- **Persönlicher OAuth-Login (Authorization Code + PKCE)**: verworfen. Die leistende Person wäre automatisch korrekt und `CreatedBy` pro Person nachvollziehbar, aber jeder Nutzer bräuchte passende Objektrechte und einen Browser-Login-Flow in einer Desktop-App.

## Consequences

- `CreatedBy` ist in Salesforce immer der technische User; wer geleistet hat, steht nur in `Person__c`.
- Consumer Key und Secret liegen bei jedem Nutzer im OS-Keyring. Technisch kann jeder Nutzer im Namen jeder Person buchen; das ist für ein internes Team akzeptiert.
- Die Rechte des Integrations-Users begrenzen, was die App insgesamt darf (Accounts und Projekte lesen, Kostenpositionen anlegen und löschen).
