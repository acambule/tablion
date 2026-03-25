Name:           tablion-file-manager
Version:        %{version}
Release:        %{release}%{?dist}
Summary:        Linux Dateimanager mit Tabgruppen, Multi-View und smarter Dateiorganisation

License:        EUPL-1.2-or-later
URL:            https://github.com/acambule/tablion
Source0:        tablion_file_manager-%{version}.tar.gz                
Source1:        tablion.desktop

BuildArch:      noarch
BuildRequires:  python3-devel python3-pyside6 python3-send2trash python3-build
Requires:       python3-pyside6 python3-send2trash

%description
Tablion ist eine einfacher Dateimanager mit Tabgruppen, Multi-View und smarter Dateiorganisation

%prep
%setup -q -n tablion_file_manager-%{version}

%build
python3 -m build --skip-dependency-check --no-isolation

%install
pip3 install --root=%{buildroot} dist/tablion_file_manager-%{version}.tar.gz

# Desktop-Datei und Icon installieren (optional, falls vorhanden)
install -D -m 644 %{SOURCE1} %{buildroot}%{_datadir}/applications/tablion.desktop


# Icon kann später ergänzt werden

%files
%license LICENSE
%doc README.md
%{_datadir}/applications/tablion.desktop
%{_bindir}/tablion-file-manager
%dir %{_prefix}/resources
%dir %{_prefix}/resources/translations
%{_prefix}/resources/translations/*.qm
%{python3_sitelib}/__pycache__/*
%{python3_sitelib}/tablion_file_manager*
%{python3_sitelib}/controllers*
%{python3_sitelib}/models*
%{python3_sitelib}/widgets*
%{python3_sitelib}/ui*
%{python3_sitelib}/utils*
%{python3_sitelib}/*.py*


%changelog
* Fri Mar 20 2026 Antonio Cambule <dev@cambule.info> - 0.8.0-1
- Automatisch aktualisiert
