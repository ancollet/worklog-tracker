# Worklog

Persönliche Zeiterfassung: Arbeitszeit wird pro Kunde und Projekt als Einträge erfasst. Die App ist das führende System; Einträge können in das Buchungssystem des Kunden übertragen und per Flag als abgerechnet markiert werden.

## Language

**Eintrag**:
Ein erfasster Zeitraum Arbeit an genau einem Projekt, mit optionalem Task und optionaler Beschreibung. Entsteht durch einen Timer oder manuell.
_Avoid_: Worklog-Element, Log, Worklog

**Laufender Eintrag**:
Ein Eintrag mit Start, aber noch ohne Ende. Es können mehrere Einträge gleichzeitig laufen; jeder zählt seine volle Zeit.
_Avoid_: aktiver Timer, der Timer

**Fortsetzen**:
Aus einem bestehenden Eintrag einen neuen, jetzt laufenden Eintrag mit demselben Projekt, Task und derselben Beschreibung erzeugen. Der ursprüngliche Eintrag bleibt unverändert, Flags werden nicht übernommen, andere laufende Einträge laufen weiter.
_Avoid_: Resume, Klonen, Neustarten

**Verschieben**:
Einen Eintrag auf einen anderen Tag legen; Uhrzeit und Dauer bleiben erhalten.
_Avoid_: Umziehen, Umbuchen

**Buchung**:
Die Übertragung genau eines Eintrags in das Buchungssystem des Kunden: bei Jira als Worklog, bei Salesforce als Kostenposition. Ein Eintrag ist gebucht oder ungebucht; "abgerechnet" ist dagegen ein Flag.
_Avoid_: Sync, Export

**Gebucht**:
Zustand eines Eintrags mit bestehender Buchung. Ein gebuchter Eintrag ist gesperrt: er kann nicht bearbeitet, verschoben, gelöscht oder bereinigt werden, bis die Buchung storniert ist. Fortsetzen und Kopieren bleiben möglich.

**Stornieren**:
Eine Buchung aufheben und den Eintrag wieder freigeben. Bei Salesforce wird die Kostenposition dort gelöscht; bei Jira wird nur die lokale Referenz entfernt, der Worklog bleibt in Jira bestehen.
_Avoid_: Entbuchen, Buchung löschen

**Buchungssystem**:
Das System, in dem ein Kunde seine Zeiten erwartet: Jira, Salesforce oder keines. Wird am Kunden festgelegt und gilt für alle seine Projekte.

### Salesforce

**Kostenposition**:
Ein `ProjectCostItem__c` in Salesforce: geleistete Stunden einer Person an einem Tag auf einem Salesforce-Projekt. Entsteht aus genau einem Eintrag; die Menge ist immer auf halbe Stunden aufgerundet.
_Avoid_: PCI, Projektkosten, Zeitbuchung

**Registrieren**:
Einen Salesforce-Account als Kunden bzw. eines seiner offenen Salesforce-Projekte als Projekt in die App übernehmen, um darauf tracken und buchen zu können. Ein registriertes Projekt entspricht genau einem Salesforce-Projekt.
_Avoid_: Importieren, Verknüpfen, Anlegen

**Leistende Person**:
Der Salesforce-User, in dessen Namen Kostenpositionen angelegt werden (`Person__c`). Jeder Nutzer hinterlegt ihn einmalig; er ist nicht der User, mit dem sich die App technisch anmeldet.
_Avoid_: Salesforce-User, Bucher

**Service Type**:
Die Leistungsart einer Kostenposition (Consulting oder Development). Hat einen Default pro Projekt und kann pro Buchung abweichen.

**Customer Request Type**:
Eine vom Kunden vorgegebene Referenz (Freitext, z.B. "SOT-00348"), die manche Kunden auf jeder Kostenposition verlangen. Optional, fest pro Projekt.

**Snippet**:
Ein vordefinierter Kurztext (z.B. "Codereview", "Recherche"), der in die Beschreibung eines Eintrags eingefügt wird. Reiner Text: nach dem Einfügen besteht keine Verbindung mehr zwischen Eintrag und Snippet.
_Avoid_: Textbaustein, Tätigkeitsart, Quick-Text
