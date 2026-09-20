# Spec: Salesforce-Buchen

Status: ready-for-agent

Glossar: `CONTEXT.md` (Abschnitt Salesforce). Relevante Entscheidung: ADR-0002 (gemeinsamer Integrations-User).
Schwester-Spec: `.scratch/eintrags-workflow/spec.md`.

## Problem Statement

Für alle Kunden außer dem Jira-Kunden müssen meine Zeiten als Kostenpositionen in unserer Salesforce-Org landen. Heute tracke ich in der App und tippe danach jede Position von Hand in Salesforce ab: Projekt heraussuchen, Datum, Stunden, Beschreibung, Service Type, bei manchen Kunden zusätzlich den Customer Request Type. Das ist doppelte Arbeit und fehleranfällig. In der App sind Salesforce-Kunden und -Projekte bisher nur freie Textfelder für IDs, ohne Verbindung zur Org. Und nachdem ich etwas gebucht habe, hindert mich nichts daran, den Eintrag lokal zu ändern, sodass App und Buchungssystem auseinanderlaufen.

## Solution

Die App verbindet sich über eine External Client App mit einem gemeinsamen Integrations-User mit der Salesforce-Org. Nutzer **registrieren** Accounts mit offenen Projekten als Kunden und deren offene Projekte als Projekte; die IDs bleiben im Hintergrund. Einträge solcher Projekte werden per Rechtsklick, einzeln oder gesammelt, über einen Buchungsdialog als **Kostenpositionen** angelegt, im Namen der vom Nutzer hinterlegten **leistenden Person**. Ein **gebuchter** Eintrag ist gesperrt, bis die Buchung **storniert** wird; das gilt einheitlich auch für Jira-Buchungen.

## User Stories

### Verbindung und Einstellungen

1. Als Nutzer möchte ich in den Einstellungen Instance-URL, Consumer Key und Consumer Secret der External Client App hinterlegen, damit die App sich anmelden kann.
2. Als Nutzer möchte ich, dass das Consumer Secret im OS-Keyring liegt und nie in der Datenbank.
3. Als Nutzer möchte ich "Verbindung testen" klicken und eine klare Erfolgs- oder Fehlermeldung sehen.
4. Als Nutzer möchte ich meine leistende Person einmalig per Suche nach Name oder E-Mail unter den aktiven Salesforce-Usern auswählen, damit Buchungen in meinem Namen angelegt werden.
5. Als Nutzer möchte ich die gewählte leistende Person mit Namen in den Einstellungen sehen.
6. Als Nutzer möchte ich einen globalen Default für den Service Type (Consulting oder Development) festlegen.
7. Als Nutzer möchte ich, dass ohne vollständige Verbindung und leistende Person alle Salesforce-Funktionen deaktiviert sind und mir gesagt wird, was fehlt.
8. Als Nutzer möchte ich, dass der bisherige Platzhalter-Abschnitt "Salesforce" in den Einstellungen durch diese echten Einstellungen ersetzt wird.

### Registrieren

9. Als Nutzer möchte ich im Kunden-Tab "Salesforce-Account registrieren…" wählen und alle Accounts sehen, die mindestens ein offenes Projekt haben.
10. Als Nutzer möchte ich diese Liste per Namenseingabe filtern.
11. Als Nutzer möchte ich einen Account registrieren und damit einen Kunden mit Buchungssystem Salesforce erhalten, dessen Name und Account-ID übernommen sind.
12. Als Nutzer möchte ich, dass ein bereits registrierter Account in der Liste als solcher markiert und nicht doppelt registrierbar ist.
13. Als Nutzer möchte ich einen bestehenden, von Hand angelegten Kunden nachträglich mit einem Account verbinden können, damit meine bisherigen Einträge erhalten bleiben.
14. Als Nutzer möchte ich bei einem Salesforce-Kunden "Projekte registrieren…" wählen und dessen offene Salesforce-Projekte sehen.
15. Als Nutzer möchte ich ein oder mehrere Projekte auf einmal registrieren.
16. Als Nutzer möchte ich beim Registrieren pro Projekt den Default-Service-Type wählen (vorbelegt mit meinem globalen Default) und optional einen Customer Request Type als Freitext eintragen.
17. Als Nutzer möchte ich Service Type und Customer Request Type eines registrierten Projekts später ändern können.
18. Als Nutzer möchte ich, dass ein registriertes Projekt genau einem Salesforce-Projekt entspricht und nicht doppelt registrierbar ist.
19. Als Nutzer möchte ich ein bestehendes, von Hand angelegtes Projekt nachträglich mit einem Salesforce-Projekt verbinden können.
20. Als Nutzer möchte ich nie eine Salesforce-ID sehen oder tippen müssen.
21. Als Nutzer möchte ich, dass beim Öffnen des Kunden-Tabs registrierte Projekte abgeglichen und in Salesforce geschlossene Projekte sichtbar markiert werden.
22. Als Nutzer möchte ich auf ein in Salesforce geschlossenes Projekt weiter tracken können; es wird nicht automatisch archiviert.
23. Als Nutzer möchte ich, dass die App ohne Netz normal startet und trackt; nur Registrieren, Abgleich und Buchen melden den Fehler.

### Buchen

24. Als Nutzer möchte ich per Rechtsklick "In Salesforce buchen…" wählen, in beiden Tabs, für einen oder mehrere Einträge.
25. Als Nutzer möchte ich, dass der Menüpunkt nur bei Einträgen von Salesforce-Kunden erscheint; Jira-Kunden behalten "In Jira buchen…".
26. Als Nutzer möchte ich einen Buchungsdialog sehen, der pro Eintrag Datum, Projekt, Menge, Service Type, Customer Request Type und Beschreibung zeigt, damit ich vor dem Absenden prüfe, was in Salesforce landet.
27. Als Nutzer möchte ich, dass die Menge in Stunden immer auf volle oder halbe Stunden aufgerundet ist, mindestens 0,5.
28. Als Nutzer möchte ich, dass die Beschreibung als "Task: Beschreibung" vorbelegt ist, ohne Task nur die Beschreibung.
29. Als Nutzer möchte ich Menge (in 0,5er-Schritten), Service Type, Customer Request Type und Beschreibung pro Zeile im Dialog ändern können.
30. Als Nutzer möchte ich, dass nicht buchbare Einträge im Dialog ausgegraut sind, mit Grund: bereits gebucht, läuft noch, weder Task noch Beschreibung, Projekt nicht registriert, Projekt in Salesforce geschlossen.
31. Als Nutzer möchte ich, dass vor dem Buchen geprüft wird, ob die betroffenen Projekte in Salesforce noch offen sind.
32. Als Nutzer möchte ich, dass jeder Eintrag genau eine Kostenposition ergibt.
33. Als Nutzer möchte ich, dass die Kostenposition mit meiner leistenden Person, dem Tag des Eintrags als Delivery Date sowie Status Open, Skill Level Standard, Location Remote und Count against Budget angelegt wird.
34. Als Nutzer möchte ich, dass bei einer Sammelbuchung ein Fehler in einer Zeile die anderen nicht abbricht und ich pro Zeile Erfolg oder Fehlertext sehe.
35. Als Nutzer möchte ich fehlgeschlagene Zeilen im selben Dialog korrigieren und erneut buchen können.
36. Als Nutzer möchte ich, dass beim erfolgreichen Buchen die Dauer des lokalen Eintrags auf die gebuchte Menge gesetzt wird (1h10 → 1h30, Ende entsprechend), damit App und Salesforce dasselbe zeigen.
37. Als Nutzer möchte ich, dass die Spalte "Gebucht" die Nummer der Kostenposition zeigt und per Tooltip bzw. Klick zum Datensatz in Salesforce führt.
38. Als Nutzer möchte ich, dass ein doppeltes Absenden denselben Eintrag nicht zweimal bucht.

### Gebucht und Stornieren

39. Als Nutzer möchte ich, dass ein gebuchter Eintrag nicht bearbeitet, verschoben, gelöscht oder bereinigt werden kann, damit App und Buchungssystem nie auseinanderlaufen.
40. Als Nutzer möchte ich beim Versuch eine klare Meldung "Eintrag ist gebucht, erst Buchung stornieren" sehen.
41. Als Nutzer möchte ich gebuchte Einträge weiterhin fortsetzen, ihre Beschreibung kopieren und Flags setzen können (z.B. "abgerechnet").
42. Als Nutzer möchte ich per Rechtsklick "Buchung stornieren" wählen; bei Salesforce wird die Kostenposition dort gelöscht und der Eintrag freigegeben.
43. Als Nutzer möchte ich, dass ein Storno abgelehnt wird, wenn die Kostenposition in Salesforce nicht mehr den Status Open hat, mit verständlicher Meldung.
44. Als Nutzer möchte ich, dass ein Storno den Eintrag auch dann freigibt, wenn die Kostenposition in Salesforce bereits gelöscht wurde.
45. Als Nutzer möchte ich, dass nach einem Storno die aufgerundete Dauer stehen bleibt; ich kann sie danach von Hand ändern.
46. Als Nutzer möchte ich, dass bei Jira-gebuchten Einträgen dieselbe Sperre gilt und "Buchung stornieren" dort wie bisher nur die lokale Referenz entfernt, mit dem bestehenden Hinweis, dass der Worklog in Jira bleibt.
47. Als Nutzer möchte ich, dass gesperrte Einträge bei Sammelaktionen (Löschen, Verschieben, Bereinigen) die ganze Aktion verhindern bzw. ausgegraut sind, mit Grund.

## Implementation Decisions

### Anmeldung (ADR-0002)

- OAuth Client-Credentials-Flow gegen die Instance-URL mit Consumer Key und Secret. Das Zugriffstoken wird im Speicher gehalten und bei Ablauf bzw. einer 401-Antwort einmal erneuert und der Aufruf wiederholt. Kein Browser-Login, kein Refresh-Token.
- Instance-URL, Consumer Key, leistende Person (ID und Anzeigename) und globaler Default-Service-Type liegen in der Settings-Tabelle; das Secret im Keyring unter eigenem Schlüssel, analog zum Jira-Token.
- HTTP über die Standardbibliothek wie beim Jira-Client; keine neue Abhängigkeit. API-Version als Konstante. Exakte Endpunkte sind bei der Umsetzung gegen die aktuelle Salesforce-REST-Dokumentation zu prüfen.

### Module

- **Salesforce-Client** (neu, tiefes Modul): kapselt Anmeldung, Abfragen, Anlegen und Löschen. Schnittstelle in Domänenbegriffen, nicht in SOQL: Verbindung testen; Accounts mit offenen Projekten auflisten; offene Projekte eines Accounts auflisten; prüfen, welche aus einer Menge von Projekten noch offen sind; aktive User suchen; Kostenposition anlegen (liefert ID und Nummer); Kostenposition löschen (unterscheidet "nicht mehr Open", "nicht gefunden", sonstige Fehler). Feld- und Objektnamen der Org leben ausschließlich hier.
- **Buchungs-Service** (neu): baut aus Einträgen Buchungsvorschläge (Menge, Beschreibung, Service Type, Customer Request Type, Buchbarkeit mit Grund), führt bestätigte Buchungen Zeile für Zeile aus, schreibt pro Erfolg die Buchungsreferenz und die aufgerundete Dauer an den Eintrag, und storniert. Er ist der einzige Ort, der die Regeln kennt; die Dialoge zeigen nur an.
- **Sperr-Regel**: eine zentrale Prüfung "Eintrag ist gebucht". Alle schreibenden Eintrags-Operationen (Bearbeiten, Löschen einzeln und gesammelt, Verschieben, Bereinigen) fragen sie ab; Flags und Fortsetzen nicht. Sie wird in der Service-/Repository-Schicht durchgesetzt, nicht nur in der UI.

### Mengen- und Textregeln

- Menge = Dauer des Eintrags in Stunden, aufgerundet auf das nächste Vielfache von 0,5, mindestens 0,5. Eine bereits exakte halbe oder volle Stunde bleibt unverändert.
- Beschreibung = "Task: Beschreibung"; ohne Task nur Beschreibung; ohne Beschreibung nur Task; ohne beides nicht buchbar.
- Delivery Date = lokales Kalenderdatum des Starts des Eintrags.
- Feste Werte der Kostenposition: Status Open, Skill Level Standard, Location Remote, Count against Budget wahr. Tagessatz, Preis pro Einheit und alle berechneten Felder werden nicht gesendet.
- Customer Request Type wird nur gesendet, wenn er nicht leer ist.
- Lokales Aufrunden beim Buchen: Dauer = gebuchte Menge, Ende = Start + Dauer.

### Schema

- Bestehende Felder werden weiterverwendet: externe Referenz des Kunden = Account-ID; externe Referenz des Projekts = ID des Salesforce-Projekts; Buchungsreferenz des Eintrags = ID der Kostenposition, die zugehörige URL = Link zum Datensatz, der Buchungszeitpunkt wie bisher. Die Anzeige in der Spalte "Gebucht" nutzt die Nummer der Kostenposition; dafür kommt ein Feld für die Anzeige-Nummer am Eintrag hinzu.
- Neue Felder am Projekt: Default-Service-Type, Customer Request Type, Kennzeichen "in Salesforce geschlossen" mit Zeitpunkt des letzten Abgleichs.
- Eindeutigkeit: Eine Account-ID darf nur an einem Kunden, eine Salesforce-Projekt-ID nur an einem Projekt hängen (leere Werte ausgenommen).
- Alle Änderungen über das vorhandene versionierte Migrationsverfahren.

### UI

- Kunden-Tab: "Salesforce-Account registrieren…" und pro Salesforce-Kunde "Projekte registrieren…", jeweils als Auswahldialog mit Filter; die freien Textfelder für externe Referenzen werden bei Salesforce-Kunden durch Anzeige des verbundenen Accounts/Projekts plus "Verbinden…/Ändern…" ersetzt. Bei Jira-Kunden bleibt alles wie heute.
- Buchungsdialog als Tabelle mit editierbaren Zellen und Statusspalte; Netzaufrufe im Hintergrund-Thread.
- Kontextmenüs beider Tabs: "In Salesforce buchen…" bzw. "In Jira buchen…" je nach Buchungssystem des Kunden; bei gebuchten Einträgen "Buchung stornieren". Der bisherige Jira-Punkt "Jira-Buchung lokal entfernen…" geht in "Buchung stornieren" auf. Bei gemischter Auswahl (Jira- und Salesforce-Kunden) ist Buchen deaktiviert.
- Das Timer-Tab-Kontextmenü, das heute keine Buchungspunkte hat, bekommt sie ebenfalls.

### Offene Recherchepunkte (vor dem Buchungs-Ticket in einer Sandbox klären)

1. Setzt die Org-Automation Tagessatz und Preis pro Einheit selbst, wenn sie nicht gesendet werden? Gibt es weitere Pflichtfelder oder Validierungsregeln beim Anlegen?
2. Wie heißt das Statusfeld am Salesforce-Projekt, welcher Wert bedeutet "offen", und über welches Feld hängt das Projekt am Account?
3. Darf der Integrations-User Kostenpositionen mit Status Open löschen, und verhindert die Org das Löschen in anderen Status selbst?
4. Exakte Picklist-Werte (API-Namen) für Service Type, Skill Level, Location, Status.

Die Antworten ändern nur den Salesforce-Client, nicht die übrigen Module.

## Testing Decisions

- Gute Tests prüfen beobachtbares Verhalten über öffentliche Schnittstellen: was an Salesforce gesendet würde, was danach in der Datenbank steht, welche Fehler der Aufrufer sieht. Keine Tests gegen interne Hilfsfunktionen oder Qt-Widgets.
- **Ein Seam: die Service-Schicht über einer In-Memory-Datenbank** (vorhandene `conn`-Fixture), mit gefälschtem HTTP an der Transportgrenze, genau wie im bestehenden Jira-Client-Test. Der Buchungs-Service wird mit einem echten Salesforce-Client über gefälschtem Transport getestet, nicht mit einem gemockten Client.
- Getestet werden:
  - Salesforce-Client: Token holen, Wiederholung nach 401, Fehlerabbildung (Auth, Netz, Validierungsfehler der Org mit lesbarem Text), Nutzlast der Kostenposition (feste Werte, keine Preis-/Tagessatzfelder, Customer Request Type nur wenn gesetzt), Unterscheidung der Löschfehler.
  - Mengenregel als reine Funktion: 1 min → 0,5; 30 min → 0,5; 31 min → 1,0; 1h10 → 1,5; 2h → 2,0.
  - Beschreibungsregel: alle vier Kombinationen aus Task/Beschreibung.
  - Buchungsvorschläge: jeder Nicht-buchbar-Grund.
  - Buchen: Referenz und aufgerundete Dauer am Eintrag, Teilerfolg bei Sammelbuchung, kein Doppelbuchen.
  - Stornieren: Freigabe bei Erfolg, Ablehnung bei "nicht mehr Open", Freigabe bei "nicht gefunden", Jira-Variante nur lokal.
  - Sperr-Regel: Bearbeiten, Löschen (einzeln und gesammelt), Verschieben und Bereinigen werden abgelehnt; Flags und Fortsetzen funktionieren.
  - Registrieren: Kunde/Projekt mit IDs anlegen, Doppelregistrierung abgelehnt, nachträgliches Verbinden bestehender Kunden/Projekte, Abgleich markiert geschlossene Projekte.
  - Migration auf das neue Schema (Vorbild: bestehender Migrationstest).
- UI wird nicht automatisiert getestet; Abnahme durch Starten der App gegen eine Sandbox.
- Vorbilder: Tests des Jira-Clients (gefälschte HTTP-Antworten), Repository-Tests zu Buchungssystem und externen Referenzen, Migrationstest.

## Out of Scope

- Persönlicher OAuth-Login pro Nutzer (siehe ADR-0002).
- Automatisches Nachziehen lokaler Änderungen in Salesforce; Ändern bestehender Kostenpositionen.
- Zusammenfassen mehrerer Einträge zu einer Kostenposition.
- Anzeige bestehender Kostenpositionen aus Salesforce, Budget- oder Preis-Anzeige, Import fremder Buchungen.
- Automatisches Archivieren in Salesforce geschlossener Projekte; automatisches Registrieren aller Projekte.
- Customer Request Type als Auswahlliste aus Salesforce (ist Freitext).
- Konfigurierbarkeit von Skill Level, Location, Count against Budget.
- Änderungen an der Jira-Buchung selbst, abgesehen von Sperre und einheitlichem "Buchung stornieren".
- Automatisches Setzen eines Flags beim Buchen.

## Further Notes

- Reihenfolge: nach Parallel-Timer und Fortsetzen aus der Schwester-Spec, vor Kopieren/Verschieben/Snippets/LLM. Verschieben und LLM-Bereinigung müssen die hier definierte Sperr-Regel verwenden.
- Einstellungen, Registrieren, Mengen-/Textregeln, Sperr-Regel und Buchungsdialog lassen sich gegen gefälschtes HTTP vollständig bauen und testen, bevor die External Client App bereitsteht. Nur die Recherchepunkte und die Abnahme brauchen die echte Org.
- Das Consumer Secret liegt bei jedem Nutzer im Keyring; jeder Nutzer kann technisch im Namen jeder Person buchen. Das ist bewusst akzeptiert (ADR-0002). Der Integrations-User sollte in Salesforce nur die nötigen Rechte haben: Accounts, Projekte und User lesen; Kostenpositionen anlegen und löschen.
- "Nicht igus" ist keine Namensprüfung: Maßgeblich ist das Buchungssystem des Kunden.
- Paketmanager ist uv (`uv sync`, `uv run pytest`).
