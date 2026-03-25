#!/bin/sh
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR/.."

SPECFILE=${1:-tablion-file-manager.spec}
VERSION=$(grep '^version' "$PROJECT_ROOT/pyproject.toml" | cut -d'"' -f2)
RELEASE=$(grep '^release' "$PROJECT_ROOT/pyproject.toml" | cut -d'"' -f2)
DISPLAY_VERSION="$VERSION-$RELEASE"

# changelog automatisch aktualisieren (optional, ersetzt nur den ersten changelog-Eintrag)
CHANGELOG_DATE=$(LC_ALL=C date +"%a %b %d %Y")
CHANGELOG_USER="$(getent passwd $(id -u) | cut -d: -f5 | cut -d, -f1)"
[ -z "$CHANGELOG_USER" ] && CHANGELOG_USER="$USER"
CHANGELOG_MAIL="<dev@cambule.info>"
CHANGELOG_LINE="* $CHANGELOG_DATE $CHANGELOG_USER $CHANGELOG_MAIL - $VERSION-$RELEASE"
CHANGELOG_BODY="- Automatisch aktualisiert"

# Ersetze den gesamten %changelog-Block
sed -i "/^%changelog/,\$c\\
%changelog\\
$CHANGELOG_LINE\\
$CHANGELOG_BODY
" "$SCRIPT_DIR/$SPECFILE"


cd "$PROJECT_ROOT"
python3 -m build

# Kopiere aktuelle Dateien
cp "$PROJECT_ROOT/dist/tablion_file_manager-$VERSION.tar.gz" ~/rpmbuild/SOURCES/
sed -i "s|^Exec=.*|Exec=env TABLION_DISPLAY_VERSION=$DISPLAY_VERSION tablion-file-manager|" "$PROJECT_ROOT/build/tablion.desktop"
cp "$PROJECT_ROOT/build/tablion.desktop" ~/rpmbuild/SOURCES/

cp "$SCRIPT_DIR/$SPECFILE" ~/rpmbuild/SPECS/

# RPM bauen
rpmbuild -ba --define "version $VERSION" --define "release $RELEASE" ~/rpmbuild/SPECS/"$SPECFILE"
