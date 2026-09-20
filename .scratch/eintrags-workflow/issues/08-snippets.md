# 08: Snippets

**What to build:** Neben jedem Beschreibungsfeld (Timer-Tab, Quick-Start-Popup, Eintrags-Dialog) gibt es einen Button, der meine Snippets als Menü zeigt. Wähle ich "Codereview", wird aus "Login-Formular" die Beschreibung "Codereview: Login-Formular"; bei leerem Feld steht "Codereview: " da und der Cursor dahinter. Meine Snippets pflege ich in einem eigenen Dialog, den ich über "Snippets verwalten…" am Ende des Menüs erreiche. Beim ersten Start sind Codereview, Entwicklung, Istanalyse und Recherche schon da.

Spec: `.scratch/eintrags-workflow/spec.md` (Stories 44–53; Abschnitt "Snippets"). Begriff: "Snippet" in `CONTEXT.md` (reiner Text, keine Verbindung zum Eintrag).

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] Neue Snippet-Tabelle (Text, Sortierung, Anlagezeitpunkt) über eine neue Schema-Migration; bestehende Datenbanken werden migriert.
- [x] Die vier Start-Snippets werden genau einmal beim Anlegen der Tabelle eingespielt und nicht erneut, wenn der Nutzer sie löscht.
- [x] Eine reine Funktion "Snippet anwenden" (Beschreibung + Snippet + bekannte Snippets → neue Beschreibung) kapselt die Regeln:
  - [x] leere Beschreibung → "Snippet: "
  - [x] präfixlose Beschreibung → "Snippet: Beschreibung"
  - [x] Snippet steht schon im Präfix → unverändert (Vergleich ohne Groß-/Kleinschreibung)
  - [x] anderer Snippet-Präfix vorhanden → "A, B: Beschreibung"
  - [x] ein Doppelpunkt im Freitext, dessen Teil davor kein bekanntes Snippet ist, gilt nicht als Präfix ("Fix: Login" + Codereview → "Codereview: Fix: Login")
- [x] Ein wiederverwendbares Bedienelement (Button + Menü) hängt an allen drei Beschreibungsfeldern und funktioniert mit einzeiligen und mehrzeiligen Feldern; nach dem Einfügen steht der Cursor am Ende bzw. hinter dem Präfix und das Feld hat den Fokus.
- [x] Kein Tastenkürzel; die bestehende Autovervollständigung der Beschreibung arbeitet unverändert.
- [x] Verwaltungsdialog nach dem Muster des Flags-Dialogs: anlegen, umbenennen, sortieren, löschen; leere und doppelte Texte werden abgelehnt.
- [x] "Snippets verwalten…" steht am Ende des Snippet-Menüs; nach dem Schließen des Dialogs zeigen alle Menüs den neuen Stand.
- [x] Umbenennen oder Löschen eines Snippets verändert keine bestehende Beschreibung.
- [x] Ohne Snippets zeigt das Menü nur "Snippets verwalten…".
- [x] Tests: alle Fälle der reinen Funktion; Repository (anlegen, umbenennen, sortieren, löschen); Migration inkl. einmaligem Startbestand (Vorbild: bestehender Migrationstest).
