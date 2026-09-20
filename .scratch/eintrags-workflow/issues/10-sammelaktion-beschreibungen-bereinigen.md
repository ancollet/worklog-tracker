# 10: Sammelaktion "Beschreibungen bereinigen…"

**What to build:** Bevor ich eine Woche abrechne, markiere ich ihre Einträge, klicke mit rechts und wähle "Beschreibungen bereinigen…". Ein Dialog listet alle gewählten Einträge mit Vorher und Nachher; die Vorschläge füllen sich Zeile für Zeile, während die App bedienbar bleibt. Pro Zeile entscheide ich über Übernehmen oder Verwerfen; erst dann wird gespeichert.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 60–62, 65–67).

**Blocked by:** 01 (Gemeinsames Eintrags-Kontextmenü), 09 (LLM-Bereinigung im Eintrags-Dialog)

**Status:** ready-for-agent

- [ ] Menüpunkt "Beschreibungen bereinigen…" im gemeinsamen Kontextmenü, für einen oder mehrere Einträge; deaktiviert ohne vollständige LLM-Konfiguration.
- [ ] Der Dialog zeigt pro Eintrag Datum, Task, Vorher, Nachher und eine Auswahl Übernehmen/Verwerfen.
- [ ] Ein LLM-Aufruf pro Eintrag über den Service aus Ticket 09, im Hintergrund; die Zeilen füllen sich einzeln, mit sichtbarem Fortschritt.
- [ ] Einträge ohne Beschreibung sind ausgegraut mit Grund und lösen keinen Aufruf aus. Die Prüfung ist so gebaut, dass weitere Ausschlussgründe (gebucht, kommt mit der Salesforce-Spec) an derselben Stelle ergänzt werden können.
- [ ] Zeilen mit unverändertem Ergebnis zeigen "bereits sauber" und sind nicht zur Übernahme vorausgewählt.
- [ ] Ein Fehler in einer Zeile zeigt den Fehlertext in dieser Zeile und bricht die übrigen nicht ab; ein Konfigurations-/Auth-Fehler bricht den Lauf mit einer Meldung ab, statt ihn pro Zeile zu wiederholen.
- [ ] "Alle übernehmen" und "Alle verwerfen" als Komfortfunktion; gespeichert werden nur übernommene Zeilen, und nur das Feld Beschreibung.
- [ ] Abbrechen bzw. Schließen während des Laufs stoppt weitere Aufrufe und speichert nichts.
- [ ] Laufende Einträge dürfen bereinigt werden; sie laufen danach weiter.
- [ ] Nach dem Speichern sind Baum und Logs-Tab aktuell.
- [ ] Tests auf Service-Ebene mit gefälschtem HTTP: mehrere Einträge mit Teilerfolg, Eintrag ohne Beschreibung wird übersprungen, nur übernommene Zeilen verändern die Datenbank.
