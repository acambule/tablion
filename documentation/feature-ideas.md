# Feature-Ideen

Liste von möglichen Features für die Zukunft

## Feature-Idee: Zusätzliche Spalten im FileTree

Aktuell können im FileTree Spalten ein-/ausgeblendet werden (persistiert), aber die verfügbaren Spalten basieren noch auf den Standardwerten des `QFileSystemModel`.

### Mögliche Erweiterung

Zusätzliche, in Dateimanagern übliche Spalten anbieten, z. B.:

- Erstellungsdatum
- Letzter Zugriff
- Berechtigungen
- Eigentümer
- Gruppe
- Dateiendung
- MIME-/Inhaltstyp
- Größe auf Datenträger
- Anzahl Unterobjekte (bei Ordnern)
- Symlink-Ziel

### Technischer Hinweis

Da `QFileSystemModel` nur begrenzte Standardspalten liefert, ist dafür voraussichtlich ein eigenes Model (oder Proxy-Model) nötig, das zusätzliche Dateiattribute bereitstellt.

### Akzeptanzkriterien (Vorschlag)

- Zusätzliche Spalten sind im Header-Kontextmenü auswählbar.
- Auswahl bleibt persistent gespeichert.
- Spaltenüberschriften sind lokalisierbar (DE/EN).
- Performance bleibt bei großen Verzeichnissen nutzbar (keine spürbaren UI-Hänger).

----

## Feature-Idee: Multifile Rename

----

## Feature-Idee: Remote-Papierkorb für Cloud-Einträge

Für Remote-Clouds soll es pro `Cloud`-Eintrag einen Zugriff auf den zugehörigen Remote-Papierkorb geben.

### Zielbild

- Im Kontextmenü eines `Cloud`-Eintrags gibt es einen Befehl `Papierkorb öffnen`.
- Der Papierkorb wird als virtueller Remote-Ort im FileTree geöffnet.
- Dort sollen je nach API-Unterstützung spezielle Aktionen verfügbar sein:
  - `Wiederherstellen`
  - `Endgültig löschen`

### Fachliche Idee

- Remote-Löschen landet serverseitig typischerweise im OneDrive-/SharePoint-Papierkorb.
- Dieser Papierkorb ist kein normaler Ordnerpfad wie lokale Verzeichnisse, sondern ein separater API-Bereich.
- Tablion soll diesen Bereich deshalb als Spezialkontext behandeln, ähnlich wie ein virtueller Ort.

### API-Stand / Annahmen

- Für OneDrive Personal ist Wiederherstellen per Microsoft Graph grundsätzlich möglich.
- Für SharePoint-/Team-Kontexte ist der Zugriff auf den Papierkorb in Graph derzeit eher über `beta` abbildbar.
- Der `beta`-Status wird für dieses Feature bewusst akzeptiert.

### Technische Hinweise

- Eigener Remote-Kontexttyp für Papierkorb sinnvoll, statt ihn als normalen Ordnerpfad zu behandeln.
- Eigene Kontextmenüs im Papierkorb nötig.
- Wiederherstellen und endgültiges Löschen hängen vom jeweiligen Provider und Scope ab.
- Für SharePoint/Teams sollte klar kenntlich sein, dass die Implementierung auf Graph-`beta` basiert.

### Offene Fragen

- Soll der Papierkorb nur über das Kontextmenü des Mounts erreichbar sein oder zusätzlich als eigener untergeordneter Navigator-Eintrag?
- Wie sollen gemischte Fälle behandelt werden, wenn Provider oder konkrete Mount-Typen keinen Papierkorb-Zugriff erlauben?
- Welche Metadaten werden im Papierkorb angezeigt, z. B. ursprünglicher Pfad oder Löschdatum?

----

## Feature-Idee: Temporäre Remote-Bearbeitung mit Rückupload

Für bestimmte Remote-Dateitypen soll Tablion ein lokales Bearbeiten ohne Vollsync ermöglichen, ähnlich wie bei FTP-/SFTP-Clients wie FileZilla.

### Zielbild

- Remote-Datei wird temporär lokal heruntergeladen.
- Datei wird mit der lokalen Standardanwendung geöffnet.
- Wenn die Datei lokal geändert wurde, erkennt Tablion das.
- Danach bietet Tablion an, die geänderte Datei wieder auf das Remote hochzuladen.

### Abgrenzung

- Das ist **kein** permanenter Sync.
- Es gibt keinen dauerhaften bidirektionalen Hintergrundabgleich.
- Das Verhalten ist eher eine **Remote Edit Session**:
  - herunterladen
  - lokal bearbeiten
  - Änderung erkennen
  - Rückfrage zum Upload

### Sinnvolle Einsatzfälle

- Textdateien
- Markdown / JSON / YAML / Konfigurationsdateien
- PDFs
- Bilder
- Dateien, die sich nicht sinnvoll in einer Web-/PWA-Anwendung bearbeiten lassen

Für Office-Dateien (`docx`, `xlsx`, `pptx`) kann weiterhin Web/PWA der bevorzugte Standard bleiben.

### Möglicher Ablauf

1. Remote-Datei öffnen im Modus `lokal bearbeiten`
2. Datei temporär in einen lokalen Cache herunterladen
3. Mit lokaler Standardanwendung öffnen
4. Dateiänderungen erkennen, z. B. über `mtime`, Hash oder Dateiwatcher
5. Rückfrage:
   - `Änderungen auf Remote hochladen?`
6. Bei Bestätigung Datei wieder hochladen

### Technische Hinweise

- Eigene Schicht für Edit-Sessions sinnvoll, z. B.:
  - lokaler Temp-Pfad
  - zugehörige Remote-ID / Remote-Pfad
  - ursprüngliche Remote-Metadaten (`eTag`, `lastModifiedDateTime`)
  - lokaler Ausgangs-Hash / Zeitstempel
- Für Konflikte sollte vor Upload geprüft werden, ob die Remote-Datei zwischenzeitlich geändert wurde.
- Für das Erkennen lokaler Änderungen sind Dateiwatcher oder `mtime`-/Hash-Prüfungen denkbar.
- Alte Temp-Dateien und Sessions brauchen eine Cleanup-Strategie.

### UX-Idee

- Remote-Dateizuordnungen könnten um einen Modus erweitert werden:
  - `Web/PWA öffnen`
  - `Lokal temporär bearbeiten`
  - optional später `Fragen`

### Offene Fragen

- Soll der Upload sofort bei jeder Änderung angeboten werden oder erst beim Fokuswechsel / Schließen?
- Wie sollen Konflikte zwischen lokaler Bearbeitung und zwischenzeitlicher Remote-Änderung dargestellt werden?
- Wo werden aktive Remote-Edit-Sessions sichtbar gemacht, falls mehrere parallel offen sind?
