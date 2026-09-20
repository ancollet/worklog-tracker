# 07: Drag & Drop im Baum

**What to build:** Im Baum des Timer-Tabs ziehe ich einen oder mehrere Einträge mit der Maus auf einen anderen Tag: entweder auf die Tageszeile oder auf irgendeinen Eintrag dieses Tages. Die Einträge liegen danach auf diesem Tag, mit unveränderter Uhrzeit und Dauer.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 33–36, 41–43).

**Blocked by:** 06 (Verschieben auf… (Datumsauswahl))

**Status:** ready-for-agent

- [x] Ziehbar sind nur Eintragszeilen; Monats- und Tageszeilen lassen sich nicht ziehen.
- [x] Drop-Ziele sind Tageszeilen und Eintragszeilen (Ziel ist deren Tag); Monatszeilen und der leere Bereich nehmen keinen Drop an, der Cursor zeigt das an.
- [x] Eine Mehrfachauswahl wird gemeinsam verschoben.
- [x] Laufende Einträge sind nicht ziehbar; ist einer Teil der gezogenen Auswahl, wird nichts verschoben und der Grund angezeigt.
- [x] Der Drop ruft ausschließlich die Verschieben-Operation aus Ticket 06 auf; der Baum wird danach aus der Datenbank neu aufgebaut und nicht von Qt intern umgehängt (keine Einträge unter Einträgen, keine verlorenen Chips).
- [x] Drop auf den eigenen Tag ändert nichts.
- [x] Aufgeklappte/zugeklappte Monate und Tage sowie die Scrollposition bleiben nach dem Drop erhalten, soweit die Zeilen noch existieren.
- [x] Doppelklick, Rechtsklick und Mehrfachauswahl im Baum funktionieren unverändert.
- [ ] Von Hand geprüft: einzelner Eintrag, Mehrfachauswahl, Drop auf Tageszeile, Drop auf Eintrag, Drop auf Monat (abgelehnt), laufender Eintrag (abgelehnt).

**Verifikation (Agent):** Offscreen (`QT_QPA_PLATFORM=offscreen`) mit echten `QDragEnterEvent`/`QDragMoveEvent`/`QDropEvent` und den MimeData des Baums geprüft, sowohl direkt an den Handlern als auch per `sendEvent` über den Viewport: Drop auf Tageszeile, Eintragszeile, Monatszeile (abgelehnt), leeren Bereich (abgelehnt), eigener Tag (keine Änderung, kein Refresh), Mehrfachauswahl, Auswahl mit laufendem bzw. gebuchtem Eintrag (nichts verschoben, Grund im Hinweis), Flags je Zeilentyp, Neuaufbau samt Chips und Summen, Auf-/Zuklapp-Zustand und Scrollposition, Doppelklick, Rechtsklick, Strg-Klick.

**Nicht verifiziert:** echtes Ziehen mit der Maus (`QDrag.exec`), das tatsächliche Cursorbild ("verboten" folgt aus dem ignorierten `dragMoveEvent`, wurde aber nicht gesehen) und der Drop-Indikator. Deshalb bleibt der letzte Punkt offen.
