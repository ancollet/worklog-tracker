# 06: Verschieben auf… (Datumsauswahl)

**What to build:** Ein Eintrag ist am falschen Tag gelandet. Ich klicke im Baum des Timer-Tabs mit rechts auf einen oder mehrere Einträge, wähle "Verschieben auf…", suche ein Datum aus, und die Einträge liegen auf diesem Tag, auch wenn der Tag bisher keine Einträge hatte. Die Uhrzeit bleibt, nur das Datum ändert sich; Dauer, Rundung und "manuell" bleiben unverändert.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 37–43; Abschnitt "Verschieben"). Begriff: "Verschieben" in `CONTEXT.md`.

**Blocked by:** 01 (Gemeinsames Eintrags-Kontextmenü)

**Status:** ready-for-agent

- [x] Eine Service-Operation nimmt eine Liste von Eintrags-IDs und ein Zieldatum und verschiebt Start und Ende jedes Eintrags auf das Zieldatum bei gleicher lokaler Uhrzeit.
- [x] Die lokale Uhrzeit bleibt auch über eine Sommer-/Winterzeit-Grenze erhalten (Datum ersetzen, nicht Vielfache von 24 h addieren); die gespeicherte Dauer bleibt unverändert.
- [x] Einträge, die über Mitternacht gehen, behalten ihre Länge; maßgeblich für "Tag des Eintrags" ist der Start.
- [x] Dauer, Rundung, Kennzeichen "manuell", Flags, Task, Beschreibung und Projekt bleiben unverändert.
- [x] Die Operation ist atomar: Enthält die Auswahl einen laufenden Eintrag, wird nichts verschoben und der Grund zurückgegeben. Die Prüfung ist so gebaut, dass weitere Sperrgründe (gebucht, kommt mit der Salesforce-Spec) an derselben Stelle ergänzt werden können.
- [x] Überlappungen am Zieltag werden nicht geprüft.
- [x] Menüpunkt "Verschieben auf…" im Kontextmenü des Timer-Tabs mit Datumsauswahl (vorbelegt mit dem Tag des angeklickten Eintrags); Abbrechen ändert nichts.
- [x] Verschieben auf denselben Tag ist ein No-op ohne Fehlermeldung.
- [x] Nach dem Verschieben sind Baum, Tages-/Monatssummen, "Heute/Diese Woche" und der Logs-Tab aktuell.
- [x] Tests auf Service-Ebene: Uhrzeit bleibt, Dauer bleibt, mehrere Einträge mit unterschiedlichen Quelltagen, leerer Zieltag, Atomarität bei laufendem Eintrag, Sommerzeit-Grenze, Eintrag über Mitternacht.
