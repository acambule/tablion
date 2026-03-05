
# Tablion


![Tablion](/assets/tablion-icon.png){ width="256" height="256" style="display: block; margin: 0 auto" }

## Entwicklung

Datei                     | UI                       | Beschreibung
------------------------- | ------------------------ | ------------
main.py                   | MainWindow \| main.ui    | App-Entry + MainWindow-Orchestrierung; lädt `main.ui`, verdrahtet Toolbar/Navigator/Session und delegiert Gruppen- und Split-Verhalten an spezialisierte Komponenten.
group_controller.py       |                          | Gruppenverwaltung (Controller): Erzeugen/Schließen/Umbenennen von Gruppen, Sichtbarkeit/Präsentation der Gruppentabs, Zugriff auf Gruppe 0, Transfer-Logik beim Schließen, und Gruppierungsregeln (inkl. verhaltensgesteuerte Neuerstellungsoption).
file_system_model.py       |                          | Spezielles QFileSystemModel mit erweitertem Drag‑&‑Drop: MIME‑Payload‑Debug, interne/externe Pfadstaging für Flatpak, spezielle Drop‑Handling‑Policy.
models/editor_settings.py |                          | Persistenz der Nutzerpräferenzen (Sprache, Tab-Close-Icons, neue Gruppen-Verhaltenswahl etc.) mit JSON‑Speicherung und Update-API.
models/file_operations.py |                          | Helferfunktionen für gängige Dateioperationen (Kopieren, Löschen, Umbenennen) mit Fehlerbehandlung.
widgets/settings_dialog.py|settings.ui               | Settings-Dialog-UI; lädt `settings.ui`, bindet Controls an `EditorSettings`, handhabt Anwendung/OK und Session‑/Reset‑Buttons.
widgets/about_dialog.py   |about.ui                  | Zeigt Informationsdialog mit Versionsangaben, Pfadeinstellungen und Hilfetext an.
widgets/manage_tab_groups_dialog.py|manageTabGoups.ui | Dialog zur Benennung/Umbennenung von Tabgruppen inklusive Iconauswahl.
group_workspace_widget.py | GroupWorkspaceWidget     | Gruppeninterne UI-Logik: enthält primäres Pane plus Split-Layouts (Einzel/2/4), aktives Sub-Pane per Fokus, Inaktiv-Ausgrauung sowie Split-State Export/Restore.
pane_controller.py        | pane.ui                   | Logik eines einzelnen Datei-Panes: Tab-Verwaltung im Pane, Dateibaum-Navigation, Back/Up-History, View-Modi (Details/Liste/Icons), State-Export/Import, erweiterte Kontextmenüs (inkl. Gruppieren/Tab-Aktionen), Drag/Drop und Rubber-Band-Auswahl, DND-debugging und Fokusrouting.
navigator.py              |                          | Seitenleiste/Navigator-Management; Laden/Speichern von `navigator.json`, Aufbau dynamischer/statischer Gruppen (Orte/Cloud/Laufwerke), Drag&Drop externer Ordner (Flatpak staging), Kontextmenüs, Persistenz des Navigator-Zustands.
localization.py           |                          | Übersetzungs‑Infrastructure, Hilfsfunktionen `app_tr`, Sprachwechsel, Standardtexte.
debug_log.py              |                          | Einfache Protokollierung / Debug-Ausgaben in Datei, verwendet von diversen Komponenten um Laufzeitinformationen zu sammeln.
single_application.py     |                          | Stellt sicher, dass nur eine Instanz der Anwendung läuft (Mutex & IPC).
utils/xdg_defaults.py     |                          | Hilfsfunktionen zum Ermitteln und Setzen von Standardanwendungen gemäß XDG.
path_bar.py               | PathBar                  | Custom PathBar-Widget: Breadcrumbs + Edit-Modus; kontext­sensitive Autovervollständigung incl. Dateiordner, klickbare Pfeile mit Unterordner­menüs und Überlauf-Submenü, Path-Activation-Signal, Drag von Breadcrumb-Pfaden, eigenes Styling.
