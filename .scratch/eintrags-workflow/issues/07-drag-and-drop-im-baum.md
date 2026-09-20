# 07: Drag & Drop im Baum

**What to build:** Im Baum des Timer-Tabs ziehe ich einen oder mehrere Einträge mit der Maus auf einen anderen Tag: entweder auf die Tageszeile oder auf irgendeinen Eintrag dieses Tages. Die Einträge liegen danach auf diesem Tag, mit unveränderter Uhrzeit und Dauer.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 33–36, 41–43).

**Blocked by:** 06 (Verschieben auf… (Datumsauswahl))

**Status:** ready-for-agent

- [ ] Ziehbar sind nur Eintragszeilen; Monats- und Tageszeilen lassen sich nicht ziehen.
- [ ] Drop-Ziele sind Tageszeilen und Eintragszeilen (Ziel ist deren Tag); Monatszeilen und der leere Bereich nehmen keinen Drop an, der Cursor zeigt das an.
- [ ] Eine Mehrfachauswahl wird gemeinsam verschoben.
- [ ] Laufende Einträge sind nicht ziehbar; ist einer Teil der gezogenen Auswahl, wird nichts verschoben und der Grund angezeigt.
- [ ] Der Drop ruft ausschließlich die Verschieben-Operation aus Ticket 06 auf; der Baum wird danach aus der Datenbank neu aufgebaut und nicht von Qt intern umgehängt (keine Einträge unter Einträgen, keine verlorenen Chips).
- [ ] Drop auf den eigenen Tag ändert nichts.
- [ ] Aufgeklappte/zugeklappte Monate und Tage sowie die Scrollposition bleiben nach dem Drop erhalten, soweit die Zeilen noch existieren.
- [ ] Doppelklick, Rechtsklick und Mehrfachauswahl im Baum funktionieren unverändert.
- [ ] Von Hand geprüft: einzelner Eintrag, Mehrfachauswahl, Drop auf Tageszeile, Drop auf Eintrag, Drop auf Monat (abgelehnt), laufender Eintrag (abgelehnt).
