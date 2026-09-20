# Spec: Eintrags-Workflow (Parallel-Timer, Fortsetzen, Kopieren, Verschieben, Snippets, LLM-Bereinigung)

Status: ready-for-agent

Glossar: `CONTEXT.md`. Relevante Entscheidung: ADR-0001 (mehrere laufende Einträge).
Schwester-Spec: `.scratch/salesforce-buchen/spec.md` (definiert die Sperre gebuchter Einträge).

## Problem Statement

Ich arbeite oft an mehreren Tasks gleichzeitig und nehme Aufgaben von gestern wieder auf, aber die App kennt nur einen einzigen Timer: Jeder Start beendet, was gerade läuft. Um eine Aufgabe von gestern weiterzuführen, muss ich Projekt, Task und Beschreibung neu eintippen (im Timer-Tab gibt es kein "Fortsetzen"). Einträge, die am falschen Tag gelandet sind, kann ich nur über den Bearbeiten-Dialog mit Datumseingabe korrigieren. Meine Beschreibungen sind uneinheitlich: immer wiederkehrende Tätigkeitswörter tippe ich jedes Mal neu, und schnell hingeschriebene Notizen sind nicht abrechnungstauglich. Und wenn ich eine Beschreibung woanders brauche, muss ich den Eintrag öffnen und den Text von Hand markieren.

## Solution

Sechs zusammenhängende Verbesserungen rund um den Eintrag, in dieser Reihenfolge umzusetzen:

1. **Mehrere laufende Einträge**: Beliebig viele Einträge laufen parallel, jeder zählt seine volle Zeit. Der Timer-Tab zeigt eine Liste "Läuft gerade", das Tray-Menü stoppt einzeln oder alle.
2. **Fortsetzen**: Rechtsklick auf einen Eintrag startet einen neuen laufenden Eintrag mit demselben Projekt, Task und derselben Beschreibung, ohne etwas anderes zu stoppen.
3. **Beschreibung kopieren**: Rechtsklick kopiert die Beschreibung(en) in die Zwischenablage.
4. **Verschieben**: Einträge per Drag & Drop oder "Verschieben auf…" auf einen anderen Tag legen.
5. **Snippets**: Vordefinierte Kurztexte per Button als Präfix in die Beschreibung einfügen.
6. **LLM-Bereinigung**: Beschreibungen per Azure OpenAI in einen knappen, abrechnungstauglichen Stil bringen, immer mit Vorher/Nachher-Vorschau.

## User Stories

### Mehrere laufende Einträge

1. Als Nutzer möchte ich einen neuen Eintrag starten, ohne dass ein laufender Eintrag gestoppt wird, damit ich parallele Arbeit korrekt erfasse.
2. Als Nutzer möchte ich im Timer-Tab eine Liste "Läuft gerade" mit allen laufenden Einträgen sehen, damit ich weiß, was gerade Zeit zählt.
3. Als Nutzer möchte ich pro laufendem Eintrag Projekt, Task, Beschreibung und eine eigene laufende Uhr sehen, damit ich die Einträge auseinanderhalten kann.
4. Als Nutzer möchte ich jeden laufenden Eintrag einzeln über seinen eigenen Stop-Button stoppen, damit die anderen weiterlaufen.
5. Als Nutzer möchte ich, dass das Eingabeformular im Timer-Tab immer einen neuen Eintrag startet und nie etwas stoppt, damit das Verhalten vorhersehbar ist.
6. Als Nutzer möchte ich einen laufenden Eintrag per Doppelklick im normalen Eintrags-Dialog bearbeiten, damit ich Task oder Beschreibung nachschärfen kann, ohne ihn zu stoppen.
7. Als Nutzer möchte ich, dass ein Eintrag mit identischem Projekt, Task und identischer Beschreibung nicht zweimal gleichzeitig laufen kann, damit ein Doppelklick keine doppelte Zeit erzeugt.
8. Als Nutzer möchte ich beim blockierten Doppelstart den Hinweis "läuft bereits" sehen, damit ich verstehe, warum nichts passiert ist.
9. Als Nutzer möchte ich, dass ein Klick auf das Tray-Icon immer das Quick-Start-Popup öffnet, damit ich schnell einen weiteren Eintrag starten kann.
10. Als Nutzer möchte ich im Tray-Menü alle laufenden Einträge sehen und jeden einzeln stoppen können, damit ich das Hauptfenster nicht öffnen muss.
11. Als Nutzer möchte ich im Tray-Menü "Alle stoppen" haben, damit ich zum Feierabend mit einem Klick fertig bin.
12. Als Nutzer möchte ich am Tray-Icon erkennen, ob mindestens ein Eintrag läuft, und im Tooltip die Anzahl sehen.
13. Als Nutzer möchte ich, dass das Quick-Start-Popup nur noch neue Einträge startet, damit es einfach bleibt; "Aktuellen Eintrag bearbeiten" und "Task wechseln" entfallen.
14. Als Nutzer möchte ich, dass nach einem Neustart der App alle zuvor laufenden Einträge weiterlaufen, damit kein Timer verloren geht.
15. Als Nutzer möchte ich, dass Tages- und Wochensummen jeden Eintrag mit voller Dauer zählen, auch wenn die Summe die Wanduhrzeit übersteigt.
16. Als Nutzer möchte ich, dass jeder gestoppte Eintrag weiterhin mit der Rundung seines Projekts (bzw. der Default-Rundung) gerundet wird.

### Fortsetzen

17. Als Nutzer möchte ich im Baum des Timer-Tabs per Rechtsklick "Fortsetzen ▶" als obersten Menüpunkt haben, damit ich die Aufgabe von gestern mit einem Klick wieder aufnehme.
18. Als Nutzer möchte ich, dass Fortsetzen Projekt, Task und Beschreibung übernimmt und den neuen Eintrag jetzt startet.
19. Als Nutzer möchte ich, dass Fortsetzen keine Flags übernimmt, damit Status-Flags wie "abgerechnet" nicht auf der Fortsetzung landen.
20. Als Nutzer möchte ich, dass Fortsetzen nie eine Buchungsreferenz übernimmt, damit die Fortsetzung ungebucht ist.
21. Als Nutzer möchte ich, dass Fortsetzen keinen anderen laufenden Eintrag stoppt und keine Rückfrage stellt.
22. Als Nutzer möchte ich, dass der ursprüngliche Eintrag unverändert bleibt.
23. Als Nutzer möchte ich, dass "Fortsetzen" bei Mehrfachauswahl deaktiviert ist, damit nicht versehentlich viele Timer starten.
24. Als Nutzer möchte ich, dass "Fortsetzen" auf einem gerade laufenden Eintrag deaktiviert ist.
25. Als Nutzer möchte ich beim Fortsetzen eines Eintrags mit archiviertem Projekt den Hinweis "Projekt ist archiviert" sehen, und es startet nichts.
26. Als Nutzer möchte ich, dass Fortsetzen im Logs-Tab (Button und Kontextmenü) exakt dasselbe tut wie im Timer-Tab.
27. Als Nutzer möchte ich auch gebuchte Einträge fortsetzen können, weil dabei ein neuer, ungebuchter Eintrag entsteht.

### Beschreibung kopieren

28. Als Nutzer möchte ich per Rechtsklick "Beschreibung kopieren" wählen, damit die Beschreibung wörtlich in der Zwischenablage landet.
29. Als Nutzer möchte ich bei Mehrfachauswahl alle Beschreibungen kopieren, eine pro Zeile in der angezeigten Reihenfolge, damit ich z.B. eine Woche zusammenfassen kann.
30. Als Nutzer möchte ich, dass leere Beschreibungen beim Kopieren übersprungen und Duplikate beibehalten werden.
31. Als Nutzer möchte ich, dass der Menüpunkt deaktiviert ist, wenn keiner der gewählten Einträge eine Beschreibung hat.
32. Als Nutzer möchte ich den Menüpunkt in beiden Tabs direkt unter "Bearbeiten…" finden, ohne Bestätigung oder Popup.

### Verschieben

33. Als Nutzer möchte ich einen Eintrag im Baum des Timer-Tabs per Drag & Drop auf eine Tageszeile ziehen, damit er auf diesem Tag liegt.
34. Als Nutzer möchte ich einen Eintrag auch auf einen beliebigen anderen Eintrag eines Tages fallen lassen können, mit demselben Ergebnis.
35. Als Nutzer möchte ich, dass Monatszeilen kein Drop-Ziel sind.
36. Als Nutzer möchte ich mehrere selektierte Einträge gemeinsam verschieben.
37. Als Nutzer möchte ich, dass beim Verschieben die Uhrzeit erhalten bleibt und sich nur das Datum ändert (Start und Ende um dieselbe Anzahl Tage).
38. Als Nutzer möchte ich, dass Dauer, Rundung und das Kennzeichen "manuell" beim Verschieben unverändert bleiben.
39. Als Nutzer möchte ich, dass Überlappungen am Zieltag nicht geprüft werden.
40. Als Nutzer möchte ich per Kontextmenü "Verschieben auf…" mit Datumsauswahl auch auf Tage ohne Einträge verschieben können.
41. Als Nutzer möchte ich, dass laufende Einträge weder ziehbar sind noch über "Verschieben auf…" verschoben werden können.
42. Als Nutzer möchte ich, dass gebuchte Einträge nicht verschoben werden können; enthält die Auswahl einen gebuchten oder laufenden Eintrag, wird nichts verschoben und der Grund genannt.
43. Als Nutzer möchte ich, dass nach dem Verschieben Baum und Summen sofort aktualisiert sind.

### Snippets

44. Als Nutzer möchte ich neben jedem Beschreibungsfeld (Timer-Tab, Quick-Start-Popup, Eintrags-Dialog) einen Button, der meine Snippets als Menü anzeigt.
45. Als Nutzer möchte ich, dass ein gewähltes Snippet als Präfix eingefügt wird: aus "Login-Formular" wird "Codereview: Login-Formular".
46. Als Nutzer möchte ich, dass bei leerem Feld "Codereview: " eingesetzt wird und der Cursor dahinter steht.
47. Als Nutzer möchte ich, dass nichts passiert, wenn dasselbe Snippet bereits im Präfix steht.
48. Als Nutzer möchte ich mehrere Snippets kombinieren können: "Codereview, Recherche: Login-Formular".
49. Als Nutzer möchte ich Snippets in einem eigenen Dialog anlegen, umbenennen, sortieren und löschen (wie im Flags-Dialog).
50. Als Nutzer möchte ich "Snippets verwalten…" am Ende des Snippet-Menüs finden.
51. Als Nutzer möchte ich beim ersten Start die Snippets Codereview, Entwicklung, Istanalyse und Recherche vorfinden.
52. Als Nutzer möchte ich, dass gelöschte oder umbenannte Snippets bestehende Beschreibungen nicht verändern, weil Snippets reiner Text sind.
53. Als Nutzer möchte ich, dass die bestehende Autovervollständigung der Beschreibung unverändert weiterarbeitet.

### LLM-Bereinigung

54. Als Nutzer möchte ich in den Einstellungen Endpoint-URL, Deployment-Name und API-Key meines Azure-OpenAI/Foundry-Modells hinterlegen.
55. Als Nutzer möchte ich, dass der API-Key im OS-Keyring liegt und nie in der Datenbank.
56. Als Nutzer möchte ich "Verbindung testen" klicken können und eine klare Erfolgs- oder Fehlermeldung sehen.
57. Als Nutzer möchte ich den kompletten Systemprompt in den Einstellungen bearbeiten und auf den Standard zurücksetzen können.
58. Als Nutzer möchte ich, dass ohne konfigurierten Key alle Bereinigen-Funktionen deaktiviert sind.
59. Als Nutzer möchte ich im Eintrags-Dialog einen "Bereinigen"-Button, der mir Vorher und Nachher zeigt, und ich entscheide über Übernehmen oder Verwerfen.
60. Als Nutzer möchte ich im Kontextmenü "Beschreibungen bereinigen…" für mehrere Einträge, mit einer Liste Vorher/Nachher und Übernehmen/Verwerfen pro Eintrag.
61. Als Nutzer möchte ich, dass die Bereinigung nie automatisch läuft.
62. Als Nutzer möchte ich, dass die UI während des LLM-Aufrufs bedienbar bleibt und ich den Fortschritt sehe.
63. Als Nutzer möchte ich, dass die Bereinigung nichts erfindet, die Sprache beibehält und Snippet-Präfixe sowie Ticket-Keys wörtlich erhält.
64. Als Nutzer möchte ich, dass nur Beschreibung und Task an das LLM gesendet werden, nie Kunden- oder Projektname.
65. Als Nutzer möchte ich bei Netz-, Auth- oder Modellfehlern eine verständliche Meldung, und meine Beschreibung bleibt unverändert.
66. Als Nutzer möchte ich, dass Einträge ohne Beschreibung und gebuchte Einträge in der Sammelaktion ausgegraut sind, mit Grund.
67. Als Nutzer möchte ich, dass ein unverändertes Ergebnis ("schon sauber") als solches angezeigt wird, statt eine leere Änderung anzubieten.

## Implementation Decisions

### Mehrere laufende Einträge (ADR-0001)

- "Laufend" wird aus den Daten abgeleitet: ein Eintrag ohne Ende läuft. Der bisherige Einzelzeiger auf den laufenden Eintrag im App-Zustand wird nicht mehr gelesen oder geschrieben; die Spalte bleibt ungenutzt liegen (kein destruktives Schema-Update).
- Der Timer-Service bekommt diese Schnittstelle: alle laufenden Einträge auflisten; starten (stoppt nichts); einen bestimmten Eintrag per ID stoppen; alle stoppen; fortsetzen per Eintrags-ID. "Wechseln" und "laufenden Eintrag bearbeiten" als Service-Operationen entfallen; laufende Einträge werden über den normalen Bearbeiten-Pfad geändert.
- Starten und Fortsetzen lehnen ab, wenn bereits ein laufender Eintrag mit identischem Projekt, Task und identischer Beschreibung existiert (Vergleich nach Trimmen; leer und nicht gesetzt gelten als gleich). Die Ablehnung ist ein eigener, fangbarer Fehlertyp, den die UI als Hinweis "läuft bereits" anzeigt.
- Stoppen rundet wie bisher pro Eintrag mit der Rundung des Projekts bzw. der Default-Rundung.
- Timer-Tab: Die eine große Uhr und der Start/Stop-Umschalter werden durch die Liste "Läuft gerade" (je Zeile Projekt-Chip, Task, Beschreibung, laufende Uhr, Stop-Button) plus Start-Formular ersetzt. Das Formular spiegelt nicht mehr den laufenden Eintrag wider.
- Tray: Klick öffnet Quick-Start; Menü listet laufende Einträge (je einer stoppbar) und "Alle stoppen"; Icon-Zustand "läuft" ab einem laufenden Eintrag; Tooltip nennt die Anzahl.
- Quick-Add-Popup: nur noch Modus Start.
- Summen ("Heute", "Diese Woche", Tages-/Monatszeilen, Analytics) bleiben einfache Summen der Dauern.

### Fortsetzen

- Die Logik zieht aus der Logs-Ansicht in den Timer-Service (Fortsetzen per Eintrags-ID). Beide Ansichten rufen nur noch diese Operation auf.
- Übernommen werden Projekt, Task, Beschreibung. Flags und Buchungsfelder werden nicht kopiert; das ändert das heutige (uncommittete) Verhalten, das Flags kopiert.
- Ablehnungsgründe als unterscheidbare Fehler: Projekt archiviert; identischer Eintrag läuft bereits; Quell-Eintrag läuft selbst.
- Die Stopp-Rückfrage entfällt.

### Beschreibung kopieren

- Eine reine Funktion baut aus einer geordneten Liste von Einträgen den Zwischenablage-Text (nicht-leere Beschreibungen, mit Zeilenumbruch verbunden, Duplikate bleiben). Beide Kontextmenüs nutzen sie.

### Verschieben

- Eine Service-Operation "Einträge auf Datum verschieben" nimmt eine Liste von Eintrags-IDs und ein Zieldatum, verschiebt Start und Ende jedes Eintrags um die Tagesdifferenz zwischen seinem Starttag und dem Zieldatum und lässt alles andere unverändert. Sie arbeitet atomar: Ist ein Eintrag laufend oder gesperrt (gebucht, siehe Schwester-Spec), wird nichts verschoben und der Grund zurückgegeben.
- Zeitzonen: Die lokale Uhrzeit bleibt erhalten, auch über eine Sommer-/Winterzeit-Grenze hinweg (Datum ersetzen, nicht 24-h-Vielfache addieren); die Dauer bleibt die gespeicherte Dauer.
- Drag & Drop existiert nur im Baum des Timer-Tabs. Ziehbar sind nur Eintragszeilen; Drop-Ziele sind Tageszeilen und Eintragszeilen (Ziel = deren Tag). Der Baum wird nach dem Drop aus der Datenbank neu aufgebaut, nicht von Qt intern umgehängt.
- "Verschieben auf…" öffnet eine Datumsauswahl und nutzt dieselbe Operation.

### Snippets

- Neue Tabelle für Snippets (Text, Sortierung, Anlagezeitpunkt) über eine neue Schema-Migration; die vier Start-Snippets werden nur beim Anlegen der Tabelle eingespielt (nicht erneut, wenn der Nutzer sie löscht).
- Eine reine Funktion "Snippet anwenden" kapselt die Präfix-Regeln: Beschreibung + Snippet → neue Beschreibung. Der Präfix ist der Teil vor dem ersten ": ", dessen kommagetrennte Bestandteile alle bekannte Snippets sind; sonst gilt der Text als präfixlos. Groß-/Kleinschreibung wird beim Duplikat-Vergleich ignoriert.
- Ein wiederverwendbares Bedienelement (Button + Menü) wird an alle drei Beschreibungsfelder gehängt; es funktioniert mit einzeiligen und mehrzeiligen Feldern. Kein Tastenkürzel.
- Verwaltungsdialog nach dem Muster des Flags-Dialogs.

### LLM-Bereinigung

- Neuer Service für die Bereinigung: nimmt Task und Beschreibung, liefert die bereinigte Beschreibung. HTTP über die Standardbibliothek, wie der bestehende Jira-Client; keine neue Abhängigkeit.
- Schnittstelle des Anbieters: OpenAI-kompatible Chat-Completions der Azure-v1-Schnittstelle (Endpoint + Deployment als Modellname + API-Key-Header). Exakte Pfade und Header sind bei der Umsetzung gegen die aktuelle Azure-Dokumentation zu prüfen.
- Einstellungen: Endpoint, Deployment, Systemprompt in der Settings-Tabelle; API-Key im Keyring unter eigenem Schlüssel. Der Standard-Systemprompt liegt im Code; "Zurücksetzen" löscht die gespeicherte Abweichung.
- Der Standardprompt enthält die Schutzregeln (nichts erfinden, Sprache beibehalten, Snippet-Präfixe und Ticket-Keys wörtlich, nur den bereinigten Text ohne Anführungszeichen oder Erklärung zurückgeben). Der Nutzer darf alles ändern.
- Die Antwort wird defensiv nachbearbeitet (Trimmen, umschließende Anführungszeichen entfernen); eine leere Antwort gilt als Fehler.
- Aufrufe laufen in einem Hintergrund-Thread; die Sammelaktion sendet einen Aufruf pro Eintrag und füllt die Vorschau zeilenweise.
- Übernehmen schreibt nur die Beschreibung; es gibt keine Historie des Originals.

### Übergreifend

- Beide Kontextmenüs (Baum im Timer-Tab, Tabelle im Logs-Tab) erhalten dieselben neuen Punkte in dieser Reihenfolge: Fortsetzen, Bearbeiten, Beschreibung kopieren, Verschieben auf… (nur Timer-Tab), Beschreibungen bereinigen…, dann das Bestehende.
- Schemaänderungen laufen über das vorhandene versionierte Migrationsverfahren.

## Testing Decisions

- Gute Tests prüfen beobachtbares Verhalten über öffentliche Service-Schnittstellen und den Datenbankzustand danach, nicht interne Hilfsfunktionen oder Qt-Widgets.
- **Ein Seam: die Service-Schicht über einer In-Memory-Datenbank**, mit der vorhandenen `conn`-Fixture. HTTP wird wie im bestehenden Jira-Client-Test an der Transportgrenze gefälscht.
- Getestet werden:
  - Timer-Service: paralleles Starten, Stoppen per ID, Alle stoppen, Duplikat-Blockade, Rundung pro Eintrag, Wiederaufnahme nach "Neustart" (neue Service-Instanz auf derselben DB). Der bestehende Test "Starten stoppt den vorherigen" wird durch sein Gegenteil ersetzt.
  - Fortsetzen: übernommene Felder, keine Flags, keine Buchungsfelder, Original unverändert, alle Ablehnungsgründe.
  - Verschieben: Uhrzeit bleibt, Dauer bleibt, Mehrfachverschiebung, Atomarität bei laufendem/gesperrtem Eintrag, Sommerzeit-Grenze.
  - Snippet-Anwendung als reine Funktion: leer, präfixlos, gleicher Präfix, mehrere Präfixe, Doppelpunkt im Freitext ohne Snippet-Präfix.
  - Kopier-Text als reine Funktion.
  - Snippet-Repository inkl. Migration und einmaligem Startbestand (Vorbild: bestehender Migrationstest).
  - LLM-Service mit gefälschtem HTTP: Erfolg, Nachbearbeitung der Antwort, Auth-/Netzfehler, leere Antwort, gesendete Nutzlast enthält weder Kunden- noch Projektname.
- UI (Drag & Drop, Menüs, Dialoge) wird nicht automatisiert getestet; es gibt dafür kein Vorbild im Repo. Abnahme durch Starten der App.
- Vorbilder: die bestehenden Tests für Timer-Service, Flags, Repository-Migration und Jira-Client.

## Out of Scope

- Salesforce-Buchen und die Sperre gebuchter Einträge (Schwester-Spec); diese Spec respektiert die Sperre nur, sobald sie existiert.
- Änderungen an der Jira-Anbindung.
- Drag & Drop im Logs-Tab.
- Überlappungsprüfung zwischen Einträgen; anteiliges Aufteilen paralleler Zeit.
- Platzhalter in Snippets, kunden- oder projektspezifische Snippets, Tastenkürzel für Snippets.
- Andere LLM-Anbieter, automatische Bereinigung, Historie der Originalbeschreibung, kundenspezifische Prompts.
- Entfernen der ungenutzten Spalte für den Einzelzeiger des laufenden Eintrags.

## Further Notes

- Umsetzungsreihenfolge: Parallel-Timer → Fortsetzen → (Salesforce-Buchen aus der Schwester-Spec) → Beschreibung kopieren → Verschieben → Snippets → LLM-Bereinigung. Snippets vor LLM, weil der Standardprompt Snippet-Präfixe schützen muss.
- Der Arbeitsbaum enthält umfangreiche uncommittete Änderungen (u.a. das bisherige Fortsetzen im Logs-Tab und die Buchungsanbindung). Vor dem ersten Ticket sollte dieser Stand committet werden, damit die Tickets auf einer sauberen Basis aufsetzen.
- Paketmanager ist uv (`uv sync`, `uv run pytest`).
