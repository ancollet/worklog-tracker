# 11: Abnahme gegen die Sandbox

**What to build:** Bis hierher wurde alles gegen gefälschtes HTTP und mit angenommenen Objekt- und Feldnamen gebaut. Jetzt werden die Antworten aus Ticket 03 in den Salesforce-Client eingearbeitet und der komplette Ablauf gegen die echte Org (Sandbox) durchgespielt: verbinden, leistende Person wählen, Account und Projekte registrieren, einzeln und gesammelt buchen, stornieren. Braucht die External Client App und Zugangsdaten, daher ein Ticket für einen Menschen (ein Agent kann den ersten Punkt vorbereiten).

Spec: `.scratch/salesforce-buchen/spec.md` (Abschnitte "Offene Recherchepunkte", "Further Notes").

**Blocked by:** 03 (Sandbox-Recherche), 09 (Sammelbuchung), 10 (Salesforce-Buchung stornieren)

**Status:** ready-for-human

- [ ] Alle in Ticket 03 geklärten Namen und Werte (Objekte, Felder, Statuswerte, Picklist-API-Werte, Längenbegrenzungen) sind im Salesforce-Client eingetragen; keine "Annahme"-Markierungen mehr. Änderungen betreffen nur den Client und seine Tests.
- [ ] Zeigt Ticket 03 weitere Pflichtfelder oder dass Tagessatz/Preis doch gesendet werden müssen, ist das als neues Ticket erfasst statt hier nebenbei gelöst.
- [ ] Beschreibungen und Customer Request Types, die länger sind als die Feldgrenzen der Org, werden im Buchungsdialog vor dem Absenden erkannt.
- [ ] "Verbindung testen" ist gegen die Sandbox erfolgreich; ein falsches Secret ergibt eine verständliche Meldung.
- [ ] Leistende Person per Suche gefunden und gespeichert.
- [ ] Ein Account mit offenen Projekten registriert; zwei Projekte registriert, eines mit Customer Request Type; ein bestehender Kunde nachträglich verbunden.
- [ ] Einzelbuchung: Die Kostenposition erscheint in Salesforce mit korrekter Person, Projekt, Datum, Menge, Beschreibung, Service Type und den festen Werten; Tagessatz und Preis sind von der Org gesetzt; der Link aus der Spalte "Gebucht" öffnet den Datensatz.
- [ ] Sammelbuchung mit mindestens fünf Einträgen, darunter ein absichtlich fehlerhafter: Teilerfolg wird korrekt angezeigt, erneutes Buchen funktioniert.
- [ ] Storno einer offenen Kostenposition löscht sie in Salesforce; Storno einer nicht mehr offenen wird abgelehnt; Storno einer in Salesforce von Hand gelöschten gibt den Eintrag frei.
- [ ] Ein in der Sandbox geschlossenes Projekt wird beim Abgleich markiert und lässt sich nicht bebuchen.
- [ ] Gebuchte Einträge sind gegen Bearbeiten, Löschen, Verschieben und Bereinigen gesperrt; Flags und Fortsetzen funktionieren.
- [ ] Alle automatisierten Tests laufen grün (`uv run pytest`).
