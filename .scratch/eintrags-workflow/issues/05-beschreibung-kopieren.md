# 05: Beschreibung kopieren

**What to build:** Ich klicke mit rechts auf einen oder mehrere Einträge und wähle "Beschreibung kopieren". Die Beschreibung landet wörtlich in der Zwischenablage; bei mehreren Einträgen eine Beschreibung pro Zeile in der angezeigten Reihenfolge. Kein Popup, keine Bestätigung.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 28–32).

**Blocked by:** 01 (Gemeinsames Eintrags-Kontextmenü)

**Status:** ready-for-agent

- [ ] Menüpunkt "Beschreibung kopieren" direkt unter "Bearbeiten…", in beiden Tabs.
- [ ] Ein Eintrag: die Beschreibung steht unverändert in der Zwischenablage.
- [ ] Mehrere Einträge: eine Beschreibung pro Zeile, in der Reihenfolge der Ansicht; leere Beschreibungen werden übersprungen, Duplikate bleiben erhalten.
- [ ] Hat keiner der betroffenen Einträge eine Beschreibung, ist der Menüpunkt deaktiviert.
- [ ] Der Zwischenablage-Text entsteht in einer reinen Funktion (geordnete Einträge → Text), die beide Ansichten nutzen.
- [ ] Funktioniert auch für gebuchte und laufende Einträge.
- [ ] Tests für die reine Funktion: ein Eintrag, mehrere, leere dazwischen, nur leere, Duplikate, mehrzeilige Beschreibung.
