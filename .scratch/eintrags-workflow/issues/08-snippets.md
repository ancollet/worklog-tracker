# 08: Snippets

**What to build:** Neben jedem Beschreibungsfeld (Timer-Tab, Quick-Start-Popup, Eintrags-Dialog) gibt es einen Button, der meine Snippets als Menü zeigt. Wähle ich "Codereview", wird aus "Login-Formular" die Beschreibung "Codereview: Login-Formular"; bei leerem Feld steht "Codereview: " da und der Cursor dahinter. Meine Snippets pflege ich in einem eigenen Dialog, den ich über "Snippets verwalten…" am Ende des Menüs erreiche. Beim ersten Start sind Codereview, Entwicklung, Istanalyse und Recherche schon da.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 44–53; Abschnitt "Snippets"). Begriff: "Snippet" in `CONTEXT.md` (reiner Text, keine Verbindung zum Eintrag).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Neue Snippet-Tabelle (Text, Sortierung, Anlagezeitpunkt) über eine neue Schema-Migration; bestehende Datenbanken werden migriert.
- [ ] Die vier Start-Snippets werden genau einmal beim Anlegen der Tabelle eingespielt und nicht erneut, wenn der Nutzer sie löscht.
- [ ] Eine reine Funktion "Snippet anwenden" (Beschreibung + Snippet + bekannte Snippets → neue Beschreibung) kapselt die Regeln:
  - [ ] leere Beschreibung → "Snippet: "
  - [ ] präfixlose Beschreibung → "Snippet: Beschreibung"
  - [ ] Snippet steht schon im Präfix → unverändert (Vergleich ohne Groß-/Kleinschreibung)
  - [ ] anderer Snippet-Präfix vorhanden → "A, B: Beschreibung"
  - [ ] ein Doppelpunkt im Freitext, dessen Teil davor kein bekanntes Snippet ist, gilt nicht als Präfix ("Fix: Login" + Codereview → "Codereview: Fix: Login")
- [ ] Ein wiederverwendbares Bedienelement (Button + Menü) hängt an allen drei Beschreibungsfeldern und funktioniert mit einzeiligen und mehrzeiligen Feldern; nach dem Einfügen steht der Cursor am Ende bzw. hinter dem Präfix und das Feld hat den Fokus.
- [ ] Kein Tastenkürzel; die bestehende Autovervollständigung der Beschreibung arbeitet unverändert.
- [ ] Verwaltungsdialog nach dem Muster des Flags-Dialogs: anlegen, umbenennen, sortieren, löschen; leere und doppelte Texte werden abgelehnt.
- [ ] "Snippets verwalten…" steht am Ende des Snippet-Menüs; nach dem Schließen des Dialogs zeigen alle Menüs den neuen Stand.
- [ ] Umbenennen oder Löschen eines Snippets verändert keine bestehende Beschreibung.
- [ ] Ohne Snippets zeigt das Menü nur "Snippets verwalten…".
- [ ] Tests: alle Fälle der reinen Funktion; Repository (anlegen, umbenennen, sortieren, löschen); Migration inkl. einmaligem Startbestand (Vorbild: bestehender Migrationstest).
