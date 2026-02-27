# TABLION Build

----

**1. Projekt vorbereiten**

- Projektstruktur:
  ```
  file-manager/
  ├── pyproject.toml
  ├── README.md
  ├── LICENSE
  ├── src/
  │   └── ... (Python-Code)
  ├── assets/
  │   └── tablion-icon.png
  ├── tablion.desktop   # Desktop-Integration
  ```

- Wichtige Dateien:
  - pyproject.toml: Python-Projektbeschreibung und Abhängigkeiten
  - `README.md`: Projektinfo
  - `LICENSE`: Lizenz
  - `tablion.desktop`: Desktop-Startdatei (für Menüintegration)
  - tablion-icon.png: Programmsymbol

---

**2. Python-Build ausführen**

- Im Projektordner:
  ```
  python3 -m build
  ```
- Ergebnis:  
  - `dist/tablion-1.0.0.tar.gz` (Source)
  - `dist/tablion-1.0.0-py3-none-any.whl` (Wheel)

---

**3. RPM-Build-Umgebung anlegen**

- Im Terminal:
  ```
  rpmdev-setuptree
  ```
- Struktur:
  ```
  ~/rpmbuild/
  ├── BUILD/
  ├── BUILDROOT/
  ├── RPMS/
  ├── SOURCES/
  ├── SPECS/
  ├── SRPMS/
  ```

---

**4. Dateien ablegen**

- Kopiere:
  - `dist/tablion-1.0.0.tar.gz` → `~/rpmbuild/SOURCES/`
  - `tablion.desktop` → `~/rpmbuild/SOURCES/`
  - tablion-icon.png → `~/rpmbuild/SOURCES/`
- Lege die RPM-Spezifikation an:
  - `~/rpmbuild/SPECS/tablion.spec`

---

**5. Beispiel `.spec`-Datei**

```spec
Name:           tablion
Version:        1.0.0
Release:        1%{?dist}
Summary:        Dateimanager mit PySide6
License:        MIT
Source0:        tablion-1.0.0.tar.gz
Source1:        tablion.desktop
Source2:        tablion-icon.png
BuildArch:      noarch
BuildRequires:  python3-devel, python3-setuptools
Requires:       python3, python3-pyside6, python3-send2trash

%description
Tablion ist ein moderner Dateimanager mit Split-View und Trash-Unterstützung.

%prep
%setup -q

%build
python3 setup.py build

%install
python3 setup.py install --root=%{buildroot} --optimize=1
# Desktop-Datei und Icon installieren
install -D -m 644 %{SOURCE1} %{buildroot}%{_datadir}/applications/tablion.desktop
install -D -m 644 %{SOURCE2} %{buildroot}%{_datadir}/icons/hicolor/128x128/apps/tablion.png

%files
%{_bindir}/tablion
%{_datadir}/applications/tablion.desktop
%{_datadir}/icons/hicolor/128x128/apps/tablion.png
%doc README.md LICENSE

%changelog
* 2026-02-26 Antonio - Initial build
```

---

**6. RPM bauen**

- Im Terminal:
  ```
  rpmbuild -ba ~/rpmbuild/SPECS/tablion.spec
  ```
- Ergebnis:  
  - RPM liegt in `~/rpmbuild/RPMS/noarch/tablion-1.0.0-1.noarch.rpm`

---

**7. Testen/Installieren**

- Installation:
  ```
  sudo dnf install ~/rpmbuild/RPMS/noarch/tablion-1.0.0-1.noarch.rpm
  ```

---

**Zusammenfassung:**  
- Projekt sauber strukturieren (Code, Desktop-Datei, Icon, README, Lizenz, pyproject.toml).
- Python-Build erzeugen (`dist/`).
- RPM-Build-Umgebung anlegen (`rpmdev-setuptree`).
- Dateien in die richtigen Ordner kopieren.
- `.spec`-Datei schreiben und ablegen.
- RPM bauen und testen.
