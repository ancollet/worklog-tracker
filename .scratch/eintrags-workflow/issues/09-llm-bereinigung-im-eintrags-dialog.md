# 09: LLM-Bereinigung im Eintrags-Dialog

**What to build:** In den Einstellungen hinterlege ich mein Azure-OpenAI/Foundry-Modell (Endpoint, Deployment, API-Key) und prüfe es mit "Verbindung testen"; den Systemprompt kann ich komplett bearbeiten und auf den Standard zurücksetzen. Im Eintrags-Dialog klicke ich "Bereinigen": Aus "login form gefixt + bissl recherche wg oauth" wird ein Vorschlag wie "Login-Formular korrigiert, Recherche zu OAuth". Ich sehe Vorher und Nachher und entscheide über Übernehmen oder Verwerfen. Während des Aufrufs bleibt die App bedienbar.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 54–59, 61–65, 67; Abschnitt "LLM-Bereinigung").

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Neuer Abschnitt "LLM" in den Einstellungen: Endpoint-URL, Deployment-Name, API-Key, Systemprompt (mehrzeilig), "Auf Standard zurücksetzen", "Verbindung testen" mit klarer Erfolgs-/Fehlermeldung.
- [ ] Der API-Key liegt im OS-Keyring unter eigenem Schlüssel, nie in der Datenbank; ist der Keyring nicht erreichbar, erscheint die bestehende verständliche Meldung statt eines Absturzes.
- [ ] Endpoint, Deployment und ein vom Standard abweichender Prompt liegen in der Settings-Tabelle; "Zurücksetzen" löscht die Abweichung.
- [ ] Ein Bereinigungs-Service nimmt Task und Beschreibung und liefert die bereinigte Beschreibung. HTTP über die Standardbibliothek, keine neue Abhängigkeit.
- [ ] Aufruf über die OpenAI-kompatible Chat-Completions-Schnittstelle von Azure; exakter Pfad, Header und Parameter sind vor der Umsetzung gegen die aktuelle Azure-Dokumentation geprüft (Context7).
- [ ] Gesendet werden ausschließlich Systemprompt, Task und Beschreibung; nie Kunden- oder Projektname.
- [ ] Der Standardprompt im Code verlangt: knapper, abrechnungstauglicher Stil; nichts erfinden; Sprache der Eingabe beibehalten; Snippet-Präfixe und Ticket-Keys wörtlich erhalten; nur den bereinigten Text zurückgeben.
- [ ] Die Antwort wird getrimmt und von umschließenden Anführungszeichen befreit; eine leere Antwort gilt als Fehler.
- [ ] "Bereinigen"-Button im Eintrags-Dialog; deaktiviert ohne vollständige LLM-Konfiguration (mit Tooltip, was fehlt) und bei leerer Beschreibung.
- [ ] Vorher/Nachher-Vorschau mit Übernehmen und Verwerfen; Übernehmen setzt nur das Beschreibungsfeld im Dialog, gespeichert wird erst mit dem normalen Speichern.
- [ ] Ist das Ergebnis identisch mit der Eingabe, wird "bereits sauber" angezeigt statt einer leeren Änderung.
- [ ] Der Aufruf läuft im Hintergrund-Thread mit sichtbarem Wartezustand; Schließen des Dialogs während des Aufrufs führt nicht zum Absturz.
- [ ] Netz-, Auth- und Modellfehler erscheinen als verständliche Meldung; die Beschreibung bleibt unverändert.
- [ ] Nie automatisch: Es gibt keinen Aufruf ohne Klick.
- [ ] Tests mit gefälschtem HTTP (Vorbild: Jira-Client-Test): Erfolg, Nachbearbeitung der Antwort, 401, Netzfehler, leere Antwort, Nutzlast enthält weder Kunden- noch Projektname, angepasster Prompt wird verwendet, Zurücksetzen liefert den Standardprompt.
