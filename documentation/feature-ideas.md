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
