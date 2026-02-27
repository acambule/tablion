
# Tablion

![Tablion](/assets/tablion-icon.png){ width="256" height="256" style="display: block; margin: 0 auto" }

## Entwicklung

Datei                     | UI                       | Beschreibung
------------------------- | ------------------------ | ------------
main.py                   | MainWindow \| main.ui    | App-Entry + MainWindow-Orchestrierung; lädt `main.ui`, verdrahtet Toolbar/Navigator/Session und delegiert Gruppen- und Split-Verhalten an spezialisierte Komponenten.
group_controller.py       |                          | Gruppenverwaltung (Controller): Erzeugen/Schließen/Umbenennen von Gruppen, Sichtbarkeit/Präsentation der Gruppentabs, Zugriff auf Gruppe 0 und Gruppierungsregeln.
group_workspace_widget.py | GroupWorkspaceWidget     | Gruppeninterne UI-Logik: enthält primäres Pane plus Split-Layouts (Einzel/2/4), aktives Sub-Pane per Fokus, Inaktiv-Ausgrauung sowie Split-State Export/Restore.
pane_controller.py        | fileTreeView \| pane.ui  | Logik eines einzelnen Datei-Panes: Tab-Verwaltung im Pane, Dateibaum-Navigation, Back/Up-History, View-Modi (Details/Liste/Icons), State-Export/Import, Pane-Kontextmenüs und Gruppierungs-Signal.
navigator.py              |                          | Seitenleiste/Navigator-Management; Laden/Speichern von `navigator.json`, Aufbau dynamischer/statischer Gruppen (Orte/Cloud/Laufwerke), Drag&Drop externer Ordner, Kontextmenüs, Persistenz des Navigator-Zustands.
path_bar.py               | PathBar                  | Custom PathBar-Widget: Breadcrumbs + Edit-Modus, Path-Autocomplete, Path-Activation-Signal, Drag von Breadcrumb-Pfaden, eigenes Styling.
