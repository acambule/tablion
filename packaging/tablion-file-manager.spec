Name:           tablion-file-manager
Version:        %{version}
Release:        %{release}%{?dist}
Summary:        Linux Dateimanager mit Tabgruppen, Multi-View und smarter Dateiorganisation

License:        EUPL-1.2-or-later
URL:            https://github.com/acambule/tablion
Source0:        tablion_file_manager-%{version}.tar.gz
Source1:        tablion.desktop

BuildArch:      noarch
BuildRequires:  pyproject-rpm-macros
BuildRequires:  python3-devel
BuildRequires:  python3dist(setuptools) >= 69
BuildRequires:  python3dist(wheel)
Requires:       python3-pyside6
Requires:       python3-send2trash

%description
Tablion ist eine einfacher Dateimanager mit Tabgruppen, Multi-View und smarter Dateiorganisation

%prep
%setup -q -n tablion_file_manager-%{version}

%generate_buildrequires
%pyproject_buildrequires

%build
%pyproject_wheel

%install
%pyproject_install
%pyproject_save_files \
  __init__ \
  backends \
  controllers \
  domain \
  models \
  remotes \
  services \
  ui \
  utils \
  widgets \
  debug_log \
  localization \
  main \
  single_application \
  version_info

# Desktop-Datei und Übersetzungen installieren
install -D -m 644 %{SOURCE1} %{buildroot}%{_datadir}/applications/tablion.desktop

%files -f %{pyproject_files}
%license LICENSE
%doc README.md
%{_bindir}/tablion-file-manager
%{_datadir}/applications/tablion.desktop
%dir %{_prefix}/resources
%dir %{_prefix}/resources/translations
%{_prefix}/resources/translations/*.qm

%changelog
* Wed Apr 08 2026 Antonio Cambule <dev@cambule.info> - 0.9.0-3
- Automatisch aktualisiert
