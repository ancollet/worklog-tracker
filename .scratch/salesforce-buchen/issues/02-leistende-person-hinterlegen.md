# 02: Leistende Person hinterlegen

**What to build:** In den Salesforce-Einstellungen suche ich einmalig nach meinem Namen oder meiner E-Mail, wähle meinen Salesforce-User aus und sehe ihn danach mit Namen angezeigt. In seinem Namen werden später alle Kostenpositionen angelegt. Eine ID sehe oder tippe ich nie.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 4–5, 7). Begriff: "Leistende Person" in `CONTEXT.md`.

**Blocked by:** 01 (Salesforce-Verbindung)

**Status:** ready-for-agent

- [ ] Der Salesforce-Client kann aktive User nach Name oder E-Mail suchen (Teiltreffer, begrenzte Trefferzahl) und liefert ID, Name und E-Mail.
- [ ] Sucheingaben werden sicher in die Abfrage eingebaut (keine Injection über Sonderzeichen wie Apostroph).
- [ ] In den Einstellungen: Suchfeld, Trefferliste, Auswahl; die gewählte Person wird mit Name (und E-Mail) angezeigt und kann geändert oder entfernt werden.
- [ ] ID und Anzeigename der leistenden Person liegen in der Settings-Tabelle.
- [ ] Die Suche ist ohne funktionierende Verbindung deaktiviert, mit Hinweis, was fehlt; sie friert die UI nicht ein.
- [ ] Die zentrale Abfrage "Salesforce ist vollständig konfiguriert" aus Ticket 01 berücksichtigt die leistende Person als Voraussetzung fürs Buchen (nicht fürs Registrieren).
- [ ] Tests mit gefälschtem HTTP: Treffer, keine Treffer, Sonderzeichen in der Eingabe, nur aktive User, Netzfehler.
