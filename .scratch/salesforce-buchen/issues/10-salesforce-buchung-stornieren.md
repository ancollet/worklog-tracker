# 10: Salesforce-Buchung stornieren

**What to build:** Ich habe einen Eintrag falsch gebucht. Per Rechtsklick wähle ich "Buchung stornieren": Die Kostenposition wird in Salesforce gelöscht und mein Eintrag ist wieder frei zum Ändern und erneuten Buchen. Ist die Kostenposition in Salesforce nicht mehr im Status Open (z.B. schon abgerechnet), wird das Storno mit einer verständlichen Meldung abgelehnt und der Eintrag bleibt gesperrt. Wurde die Kostenposition in Salesforce bereits von Hand gelöscht, wird der Eintrag trotzdem freigegeben.

Spec: `.scratch/salesforce-buchen/spec.md` (Stories 42–45). Begriff: "Stornieren" in `CONTEXT.md`.

**Blocked by:** 07 (Gebucht = gesperrt und "Buchung stornieren"), 08 (Einen Eintrag in Salesforce buchen)

**Status:** ready-for-agent

- [ ] Der Salesforce-Client löscht eine Kostenposition und unterscheidet drei Ausgänge: gelöscht, nicht gefunden, nicht mehr Open bzw. von der Org abgelehnt (mit dem Meldungstext von Salesforce), plus Netz-/Anmeldefehler.
- [ ] Vor dem Löschen wird der Status der Kostenposition geprüft; nur Status Open wird gelöscht. (Ob die Org das Löschen in anderen Status selbst verhindert, klärt Ticket 03; die App verlässt sich nicht darauf.)
- [ ] Die Stornieren-Operation aus Ticket 07 ist um das Buchungssystem Salesforce erweitert: gelöscht oder nicht gefunden → Buchungsreferenz, Link, Nummer und Buchungszeitpunkt werden entfernt, der Eintrag ist frei; abgelehnt oder Fehler → der Eintrag bleibt unverändert gesperrt.
- [ ] Rückfrage vor dem Storno nennt die Nummer der Kostenposition und dass sie in Salesforce gelöscht wird.
- [ ] Bei "nicht gefunden" wird der Nutzer informiert, dass die Kostenposition in Salesforce schon fehlte.
- [ ] Die aufgerundete Dauer bleibt nach dem Storno stehen; sie ist danach von Hand änderbar.
- [ ] Ein stornierter Eintrag lässt sich erneut buchen und ergibt eine neue Kostenposition.
- [ ] "Buchung stornieren" ist in diesem Ticket nur bei genau einem Eintrag aktiv; der Aufruf läuft im Hintergrund.
- [ ] Jira-Stornos verhalten sich unverändert wie in Ticket 07.
- [ ] Tests mit gefälschtem HTTP: Erfolg gibt frei und entfernt alle Buchungsfelder; nicht mehr Open lehnt ab und lässt den Eintrag gesperrt; nicht gefunden gibt frei; Netzfehler lässt alles unverändert; erneutes Buchen nach Storno funktioniert.
