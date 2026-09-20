# 04: Fortsetzen in beiden Tabs

**What to build:** Ich klicke mit rechts auf einen Eintrag (z.B. die Aufgabe von gestern) und wähle "Fortsetzen ▶", den obersten Menüpunkt. Sofort läuft ein neuer Eintrag mit demselben Projekt, Task und derselben Beschreibung ab jetzt. Nichts anderes wird gestoppt, es gibt keine Rückfrage, der ursprüngliche Eintrag bleibt unverändert. Das funktioniert identisch im Timer-Tab und im Logs-Tab (dort auch über den bestehenden Button).

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 17–27; Abschnitt "Fortsetzen"). Begriff: "Fortsetzen" in `CONTEXT.md`.

**Blocked by:** 01 (Gemeinsames Eintrags-Kontextmenü), 02 (Mehrere laufende Einträge im Timer-Tab)

**Status:** ready-for-agent

- [ ] Fortsetzen ist eine Operation des Timer-Service, die eine Eintrags-ID nimmt; beide Ansichten rufen nur sie auf, die bisherige Logik in der Logs-Ansicht ist entfernt.
- [ ] Übernommen werden Projekt, Task und Beschreibung. Flags werden nicht übernommen (Änderung gegenüber dem bisherigen Verhalten), Buchungsfelder nie.
- [ ] Kein anderer laufender Eintrag wird gestoppt; die Stopp-Rückfrage ist entfernt.
- [ ] Der Quell-Eintrag ist danach unverändert.
- [ ] "Fortsetzen ▶" ist oberster Punkt des gemeinsamen Kontextmenüs.
- [ ] Deaktiviert bei Mehrfachauswahl und wenn der Eintrag selbst gerade läuft.
- [ ] Bei archiviertem Projekt startet nichts; Hinweis "Projekt ist archiviert".
- [ ] Läuft bereits ein identischer Eintrag, startet nichts; Hinweis "läuft bereits".
- [ ] Die Ablehnungsgründe sind auf Service-Ebene unterscheidbare Fehler.
- [ ] Gebuchte Einträge lassen sich fortsetzen; die Fortsetzung ist ungebucht.
- [ ] Der neue Eintrag erscheint sofort in "Läuft gerade", im Baum und im Tray-Menü.
- [ ] Tests auf Service-Ebene: übernommene Felder, keine Flags, keine Buchungsfelder, Original unverändert, andere laufende Einträge laufen weiter, alle drei Ablehnungsgründe.
