---
status: accepted
---

# Mehrere laufende Einträge statt genau einem Timer

Ursprünglich konnte genau ein Eintrag laufen; jeder Start stoppte den vorherigen. In der Praxis werden Tasks aber parallel bearbeitet und sollen parallel erfasst werden, daher dürfen jetzt beliebig viele Einträge gleichzeitig laufen, und jeder zählt seine volle Zeit.

## Considered Options

- **Ein Timer, nur Überlappung manueller Einträge**: verworfen, weil paralleles Arbeiten dann nachträglich von Hand nachgebaut werden müsste.
- **Parallele Zeit anteilig aufteilen**: verworfen; gegenüber dem Kunden zählt jeder Task mit seiner vollen Dauer.

## Consequences

- Tages- und Wochensummen können die Wanduhrzeit übersteigen. Das ist gewollt, kein Fehler.
- Starten und Fortsetzen stoppen nie einen anderen Eintrag; "Task wechseln" gibt es nicht mehr.
- Einziger Schutz gegen versehentliche Doppelzählung: Ein Eintrag mit identischem Projekt, Task und identischer Beschreibung kann nicht zweimal gleichzeitig laufen.
