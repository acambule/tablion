# PaneController Refactor Plan

## Ziel

`PaneController` soll von einer fachlich überladenen Datei zu einem schlanken Orchestrator werden.
Künftig soll der Controller:

- UI-Signale entgegennehmen
- den aktuellen Pane-Kontext kennen (`local` oder `remote`)
- die passende Fachlogik ansprechen
- Ergebnisse an View und Modelle zurückgeben

Er soll nicht mehr selbst die Details von Navigation, Dateioperationen, Remote-Zugriff, Drag'n'Drop oder Öffnen-Logik implementieren.

## Status

- Phase 1 abgeschlossen
- Phase 2 abgeschlossen
- Phase 3 abgeschlossen
- Phase 4 abgeschlossen
- Phase 5 abgeschlossen
- Phase 6 weitgehend abgeschlossen
- Phase 7 begonnen

## Aktuelle Probleme

Der aktuelle `PaneController` bündelt zu viele Verantwortlichkeiten:

- lokale Navigation auf Basis von `QFileSystemModel`
- Tab- und History-Management
- Dateioperationen wie Kopieren, Verschieben, Umbenennen und Löschen
- Öffnen von Dateien und Verzeichnissen
- Archiv- und Trash-Logik
- Drag'n'Drop-Verarbeitung
- Such- und Selektionslogik
- UI-Verdrahtung und View-Zustand

Das erschwert:

- die Einführung von Remote-Drives
- das Testen einzelner Fachregeln
- das sichere Weiterentwickeln ohne Seiteneffekte
- die Wiederverwendung von Logik außerhalb des Panes

## Zielstruktur

### Controller

- `src/controllers/pane_controller.py`
  - bleibt UI-Orchestrator
  - verwaltet Tabs, aktiven View und Signal-Verdrahtung
  - delegiert Fachlogik an Services und Backends

### Domain

- `src/domain/filesystem/location.py`
  - beschreibt, wo sich ein Pane gerade befindet
- `src/domain/filesystem/entry.py`
  - backend-neutrale Repräsentation eines Eintrags
- `src/domain/filesystem/backend.py`
  - Schnittstelle für lokale und Remote-Backends

### Backends

- `src/backends/local/local_backend.py`
  - lokale Dateisystem-Implementierung
- `src/backends/remote/...`
  - später Remote-Implementierungen wie OneDrive

### Services

- `src/services/navigation/pane_navigation_service.py`
  - Navigation und Pfadauflösung
- `src/services/file_actions/...`
  - später Copy, Move, Delete, Rename, Open, Mkdir

### Remote-Modul

- `src/remotes/...`
  - Provider, Registry, Settings und Auth für Remote-Drives

## Reihenfolge des Refactors

## Phase 1: Domain- und Backend-Basis einziehen

Ziel:
- eine neutrale Schicht für Dateisystem-Kontexte schaffen
- lokale Navigation aus `PaneController` herauszulösen, ohne Verhalten zu ändern

Arbeitsschritte:
- `location.py`, `entry.py`, `backend.py` einführen
- `local_backend.py` einführen
- `pane_navigation_service.py` einführen
- `PaneController` für lokale Navigation an diese Schicht anbinden

Ergebnis:
- `PaneController` kennt nicht mehr nur rohe lokale Pfade
- die erste stabile Abstraktion für `local` und `remote` steht

## Phase 2: Navigation und Pane-Zustand sauber trennen

Ziel:
- Navigation, History und Selektionswiederherstellung aus dem Controller lösen

Arbeitsschritte:
- `history_service.py` einführen
- `selection_restore_service.py` einführen
- Navigationsregeln aus `PaneController` herausziehen
- `PaneController` auf orchestrierende Aufrufe reduzieren

Ergebnis:
- Navigation ist isoliert testbar
- lokale und Remote-Navigation können dieselben Konzepte verwenden

## Phase 3: Dateioperationen auslagern

Ziel:
- konkrete Dateioperationen aus dem Controller entfernen

Arbeitsschritte:
- Services für `copy`, `move`, `rename`, `delete`, `mkdir`, `open` einführen
- lokale Implementierungen auf `FileOperations` aufsetzen
- Controller nur noch Aktionen dispatchen lassen

Ergebnis:
- Dateioperationen sind backend-fähig vorbereitet
- Remote kann dieselben Use-Cases später implementieren

Stand nach Abschluss:
- `open`, `delete`, `batch rename`, `trash restore`, `archive`, `create`, `link`, `transfer`, `drop` und Ark-Drop sind in `src/services/file_actions/` ausgelagert
- Lösch-Policy wie Papierkorb-/Temporär-Kontext liegt nicht mehr im Controller
- `PaneController` behält in diesem Bereich nur noch UI-Orchestrierung, Feedback und View-Zustand

## Phase 4: Pane-Kontext generalisieren

Ziel:
- ein Pane kann lokal oder remote sein

Arbeitsschritte:
- `PaneLocation` als Standard im Controller etablieren
- Tabs und History auf Kontextobjekte umstellen
- PathBar und View-State an den Kontext koppeln

Ergebnis:
- `PaneController` muss nicht wissen, ob ein Ziel lokal oder remote ist

Stand nach Abschluss:
- `PaneLocation` ist der Standard in `TabState`, History und Navigation
- `PaneController` hält `current_location` als primären Kontext und spiegelt `current_directory` nur noch zur Kompatibilität
- PathBar wird über Kontextobjekte synchronisiert
- State-Import und -Export unterstützen `location`-Objekte mit Fallback auf das alte `path`-Format
- klar lokale Aktionen sind im Controller sichtbar als lokale Kontexte gekennzeichnet, statt stillschweigend auf reine Pfadannahmen zu bauen

## Phase 5: Remote-Drive-Konfiguration einführen

Ziel:
- Remote-Zugriffe in den Einstellungen verwalten und im Navigator anzeigen

Arbeitsschritte:
- `remote_drive_settings.py` einführen
- neue Settings-Seite `Remote-Clouds`
- Navigator-Einträge aus Remote-Definitionen erzeugen

Ergebnis:
- Remote-Drives sind konfigurierbar und links sichtbar
- noch ohne vollständige Dateiansicht

Stand nach Abschluss:
- Remote-Persistenz ist in Verbindungen und Einträge getrennt
- `Remote-Clouds` ist in den Einstellungen als eigener Bereich vorhanden
- Verbindungen und Einträge werden getrennt verwaltet
- OneDrive-Authentifizierung ist als erster produktiver Login-Flow vorhanden
- Navigator-Einträge werden aus Remote-Einträgen dynamisch erzeugt
- Remote-Einträge bleiben aus `navigator.json` heraus und werden nicht wie lokale Favoriten persistiert
- es gibt einen Bearbeiten-Sprung vom Navigator zurück in den passenden Remote-Eintrag der Einstellungen
- Remote-Dateizuordnungen für Browser-/PWA-Öffnen sind als eigener Einstellungs-Tab vorhanden
- Icon-Auswahl für Remote-Einträge ist konfigurierbar, inklusive Theme-Icons und eigener Icons
- der Einstellungsdialog merkt sich seine Größe und hat für `Remote-Clouds` konsistentere Abstände

## Phase 6: OneDrive als erster Provider

Ziel:
- erste echte Remote-Quelle lesbar machen

Arbeitsschritte:
- OneDrive-Provider und Graph-Client einführen
- `list_children`, `stat`, Basisnavigation umsetzen
- Remote-Eintrag im Pane anzeigen

Ergebnis:
- OneDrive kann im Pane navigiert werden

Stand nach aktuellem Ausbau:
- OneDrive wird als erster echter Remote-Provider über Microsoft Graph gelesen
- Remote-Inhalte werden im Pane in Tree- und Icon-Ansicht dargestellt
- Remote-Ordner sind im Tree aufklappbar
- PathBar unterstützt Remote-Kontexte einschließlich Root, Breadcrumbs, Overflow und Unterordner-Menüs
- Doppelklick auf Remote-Dateien ist Browser-first
- zusätzlich ist lokales Herunterladen/Öffnen weiterhin als bewusste Option vorhanden
- Remote-Dateizuordnungen erlauben das Öffnen über definierte Browser-/PWA-Kommandos mit `{url}`
- lokale Dateien und Ordner können per `Einfügen` sowie per Drag'n'Drop in einen Remote kopiert werden
- Remote-Kontextmenüs und UI-Feedback sind auf die Remote-Nutzung abgestimmt

## Phase 7: Remote-Dateioperationen

Ziel:
- Remotes im Alltag nutzbar machen

Arbeitsschritte:
- `rename`, `delete`, `mkdir`
- `copy local -> remote`
- `copy remote -> local`
- Download-/Open-Verhalten

Ergebnis:
- Remote fühlt sich im Kern wie ein Dateimanager an

Stand nach aktuellem Ausbau:
- `rename`, `delete`, `mkdir` sind für Remote implementiert
- `new file` ist für Remote implementiert
- `copy local -> remote` funktioniert über `Einfügen` und Drag'n'Drop
- `copy remote -> remote` innerhalb desselben Remote-Eintrags ist implementiert
- `move remote -> remote` innerhalb desselben Remote-Eintrags ist implementiert
- `duplicate` ist für Remote implementiert
- `copy`, `cut`, `paste`, `rename`, `delete`, `new folder`, `new file`, `duplicate` sind im Remote-Kontextmenü vorhanden

Noch offen in Phase 7:
- `remote -> local` als echter Transferpfad
- `remote -> anderer remote mount`
- `local cut -> remote` als echtes Verschieben
- internes Remote-Drag'n'Drop
- robustere Konfliktstrategien und bessere Fortschrittsanzeige für Remote-Transfers
- SharePoint-/Team-Auswahl fachlich weiter ausbauen

## Regeln für die Umsetzung

- Kein OneDrive- oder Graph-Code in `PaneController`
- Keine neuen fachlichen `Path(...)`-Sonderfälle im Controller
- Neue Logik zuerst in Service oder Backend einziehen
- Bestehendes lokales Verhalten muss nach jeder Phase weiter funktionieren
- Refactor in kleinen, stabilen Schritten statt Big Bang

## Offene Verbesserungen nach aktuellem Stand

### 1. `PaneController` weiter entschlacken

Der Controller ist deutlich besser geschnitten als zu Beginn, bleibt aber noch groß.
Vor allem diese Bereiche sind noch stark orchestrierungs- und verzweigungsintensiv:

- Kontextmenüs und Shortcut-Dispatch
- Remote-gegen-lokal-Verzweigungen
- View-spezifische UI-Entscheidungen
- einige Clipboard- und Drag'n'Drop-Verknüpfungen

Sinnvolle nächste Schritte:

- Action-Dispatch für lokal und remote weiter zusammenführen
- Menü-/Shortcut-Dispatch aus dem Controller in kleinere UI-Helfer ziehen
- verbleibende Remote-Sonderpfade stärker an Services binden

### 2. Gemeinsame Dateiaktions-Schicht für lokal und remote vertiefen

Aktuell existieren bereits viele ausgelagerte Services, aber lokal und remote laufen noch nicht überall
über dieselben fachlichen Einstiegspunkte.

Sinnvolle nächste Schritte:

- gemeinsames Action-Interface für `copy`, `move`, `rename`, `delete`, `create`, `open`
- `PaneController` entscheidet nur noch über Kontext und ruft dann dieselbe Fachaktion auf
- Remote-Aktionen aus Controller-Helfern stärker in dedizierte Services verschieben

### 3. Anzeige- und Modellschicht weiter angleichen

Aktuell:

- lokal basiert stark auf `QFileSystemModel`
- remote auf `RemoteFileTreeModel`

Das ist für den Produktstand okay, aber noch keine vollständig vereinheitlichte Pane-Schicht.

Sinnvolle nächste Schritte:

- eine stärker backend-neutrale Entry-Darstellung aufbauen
- gemeinsame Konzepte für Sortierung, Spalten und Metadaten weiter vereinheitlichen
- UI-Logik weniger von konkreten Modellimplementierungen abhängig machen

### 4. Remote-Funktionalität fachlich vervollständigen

Wichtige Ausbaupunkte:

- `remote -> local`
- `remote -> remote` über unterschiedliche Einträge/Mounts
- SharePoint-Site-/Library-Auswahl
- Team-/SharePoint-Drives präziser auswählen statt heuristisch
- Fortschritt/Abbruch für längere Remote-Operationen

### 5. Credentials und Token robuster speichern

Aktuell ist die Persistenz funktional, aber pragmatisch.

Sinnvolle nächste Schritte:

- Secret Store / Keyring statt voller Token-Persistenz in JSON
- sauberere Trennung zwischen Konfigurationsdaten und Geheimnissen
- Re-Auth/Scope-Änderungen noch klarer im UI abbilden

### 6. Dokumentation und Testpfade weiter pflegen

Mit dem gewachsenen Remote-Umfang lohnt sich ein klarer Satz Regressionstests:

- lokal
- remote persönlich
- remote Team/SharePoint
- Copy/Cut/Paste
- Drag'n'Drop
- Tab-/Split-/Session-Wiederherstellung

Die Architektur-Doku sollte nach weiteren Remote-Ausbaustufen jeweils mitgezogen werden, damit sie den realen Stand widerspiegelt und nicht wieder hinterherläuft.

## Definition von Erfolg für Phase 1

Phase 1 ist erreicht, wenn:

- es ein neutrales `Location`-Konzept gibt
- es ein erstes `LocalBackend` gibt
- `PaneController` lokale Navigation über einen Service ausführen kann
- das Verhalten aus Benutzersicht unverändert bleibt
