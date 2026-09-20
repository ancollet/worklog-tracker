# 02: Mehrere laufende Einträge im Timer-Tab

**What to build:** Ich kann im Timer-Tab einen neuen Eintrag starten, ohne dass ein laufender Eintrag gestoppt wird. Oben im Timer-Tab steht eine Liste "Läuft gerade": pro laufendem Eintrag eine Zeile mit Projekt, Task, Beschreibung, eigener laufender Uhr und eigenem Stop-Button. Das Formular darunter startet immer einen neuen Eintrag und stoppt nie etwas. Versuche ich, etwas zu starten, das mit identischem Projekt, Task und identischer Beschreibung schon läuft, passiert nichts außer dem Hinweis "läuft bereits".

Dies ist der Expand-Schritt: Die neue Schnittstelle des Timer-Service entsteht neben der alten. Tray und Quick-Add-Popup bleiben unverändert und funktionieren weiter über die alte Ein-Timer-Schnittstelle (die sich auf den zuletzt gestarteten laufenden Eintrag bezieht); sie werden in Ticket 03 umgestellt.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 1–8, 14–16; Abschnitt "Mehrere laufende Einträge"). Entscheidung: `docs/adr/0001-mehrere-laufende-eintraege.md`.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] "Laufend" wird aus den Daten abgeleitet (Eintrag ohne Ende); der Einzelzeiger im App-Zustand wird von der neuen Schnittstelle weder gelesen noch vorausgesetzt. Die Spalte bleibt bestehen.
- [ ] Der Timer-Service kann: alle laufenden Einträge auflisten, starten ohne zu stoppen, einen bestimmten Eintrag per ID stoppen, alle stoppen.
- [ ] Starten lehnt mit einem eigenen, fangbaren Fehlertyp ab, wenn ein laufender Eintrag mit identischem Projekt, Task und identischer Beschreibung existiert (Vergleich nach Trimmen; leer und nicht gesetzt gelten als gleich).
- [ ] Stoppen per ID rundet mit der Rundung des Projekts bzw. der Default-Rundung, wie bisher.
- [ ] Der Timer-Tab zeigt die Liste "Läuft gerade" mit tickender Uhr und Stop-Button pro Zeile; ohne laufende Einträge ist die Liste leer bzw. ausgeblendet.
- [ ] Das Start-Formular spiegelt keinen laufenden Eintrag mehr wider und leert bzw. behält seine Felder nach dem Start sinnvoll (Projekt bleibt, Task und Beschreibung werden geleert).
- [ ] Doppelklick auf eine Zeile in "Läuft gerade" öffnet den normalen Eintrags-Dialog; Speichern stoppt den Eintrag nicht.
- [ ] Der Hinweis "läuft bereits" erscheint im Timer-Tab beim blockierten Doppelstart.
- [ ] Nach einem Neustart der App laufen alle zuvor laufenden Einträge weiter und erscheinen in der Liste.
- [ ] Tages- und Wochensummen zählen jeden Eintrag mit voller Dauer.
- [ ] Tray und Quick-Add-Popup funktionieren weiterhin (starten, stoppen des zuletzt gestarteten Eintrags), ohne Absturz bei mehreren laufenden Einträgen.
- [ ] Tests auf Service-Ebene mit der In-Memory-DB: paralleles Starten, Stoppen per ID lässt andere laufen, Alle stoppen, Duplikat-Blockade inkl. Trim-/Leer-Regel, Rundung pro Eintrag, neue Service-Instanz auf derselben DB sieht alle laufenden Einträge. Der bestehende Test "Starten stoppt den vorherigen" wird durch sein Gegenteil ersetzt.
