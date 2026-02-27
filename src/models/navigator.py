import copy
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QModelIndex, QStandardPaths, QEvent, QObject, QSize
from PySide6.QtGui import QColor, QIcon, QPen
from PySide6.QtWidgets import QApplication, QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QMenu, QInputDialog, QLineEdit


ROLE_PATH = Qt.ItemDataRole.UserRole
ROLE_KIND = Qt.ItemDataRole.UserRole + 1
ROLE_ICON = Qt.ItemDataRole.UserRole + 2
ROLE_COLLAPSIBLE = Qt.ItemDataRole.UserRole + 3
ROLE_GROUP_NAME = Qt.ItemDataRole.UserRole + 4
ROLE_DYNAMIC = Qt.ItemDataRole.UserRole + 5
ROLE_ENTRY_TYPE = Qt.ItemDataRole.UserRole + 6
ROLE_ENTRY_DYNAMIC = Qt.ItemDataRole.UserRole + 7
ROLE_ENTRY_KEY = Qt.ItemDataRole.UserRole + 8
ROLE_ENTRY_SOURCE = Qt.ItemDataRole.UserRole + 9


DEFAULT_NAVIGATOR_DATA = {
    "groups": [
        {
            "name": "Orte",
            "active": True,
            "collapsible": False,
            "expanded": True,
            "icon": "folder-favorites",
            "entries": [
                {"label": "Persönlicher Ordner", "dynamic": "home", "icon": "user-home", "active": True},
                {"type": "separator", "label": "────────────"},
                {"label": "Papierkorb", "dynamic": "trash", "icon": "user-trash", "active": True},
                {"label": "Arbeitsfläche", "dynamic": "desktop", "icon": "user-desktop", "active": True},
                {"label": "Dokumente", "dynamic": "documents", "icon": "folder-documents", "active": True},
                {"label": "Downloads", "dynamic": "downloads", "icon": "folder-download", "active": True},
            ],
        },
        {
            "name": "Cloud",
            "active": True,
            "collapsible": True,
            "expanded": True,
            "icon": "folder-cloud",
            "entries": [
                {"label": "OneDrive", "path": "~/OneDrive", "icon": "folder-cloud"},
                {"label": "Dropbox", "path": "~/Dropbox", "icon": "folder-cloud"},
            ],
        },
        {
            "name": "Laufwerke",
            "active": True,
            "collapsible": True,
            "expanded": True,
            "dynamic": "system-drives",
            "icon": "drive-harddisk",
        },
    ]
}


class NavigatorDropIndicatorDelegate(QStyledItemDelegate):
    def __init__(self, manager, parent=None):
        super().__init__(parent)
        self.manager = manager

    def paint(self, painter, option, index):
        super().paint(painter, option, index)

        indicator_item = self.manager._drop_indicator_item
        if indicator_item is None:
            return

        current_item = self.manager.widget.itemFromIndex(index)
        if current_item is not indicator_item:
            return

        rect = option.rect
        y = rect.bottom() if self.manager._drop_indicator_draw_bottom else rect.top()

        painter.save()
        painter.setPen(QPen(QColor(110, 110, 110, 210), 2))
        painter.drawLine(rect.left() + 8, y, rect.right() - 8, y)
        painter.restore()


class NavigatorManager(QObject):
    def __init__(self, widget: QTreeWidget, data_path: Path):
        super().__init__(widget)
        self.widget = widget
        self.data_path = data_path
        self.loaded_data = {"groups": []}
        self.allowed_drop_groups = {"Orte", "Cloud"}
        self._drop_indicator_item = None
        self._drop_indicator_draw_bottom = False

    def setup(self):
        self.widget.setHeaderHidden(True)
        self.widget.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.widget.header().setStretchLastSection(True)
        self.widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.widget.customContextMenuRequested.connect(self.on_context_menu_requested)
        self.widget.setDragEnabled(True)
        self.widget.viewport().setAcceptDrops(True)
        self.widget.setDropIndicatorShown(True)
        self.widget.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.widget.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.widget.setItemDelegate(NavigatorDropIndicatorDelegate(self, self.widget))
        self.widget.viewport().installEventFilter(self)
        self.widget.clear()
        self.loaded_data = self.load_data()
        self.build_from_data(self.loaded_data)
        self.widget.itemCollapsed.connect(self.on_item_collapsed)

    def eventFilter(self, watched, event):
        try:
            if watched == self.widget.viewport():
                if event.type() == QEvent.Type.DragEnter:
                    if self.can_handle_external_folder_drop(event):
                        self.update_drop_indicator(event.position().toPoint())
                        event.acceptProposedAction()
                        return True

                if event.type() == QEvent.Type.DragMove:
                    if self.can_handle_external_folder_drop(event):
                        self.update_drop_indicator(event.position().toPoint())
                        event.acceptProposedAction()
                        return True
                    self.clear_drop_indicator()

                if event.type() == QEvent.Type.DragLeave:
                    self.clear_drop_indicator()
                    return False

                if event.type() == QEvent.Type.Drop:
                    try:
                        if self.handle_external_folder_drop(event):
                            return True
                    finally:
                        self.clear_drop_indicator()
                    return False

            return super().eventFilter(watched, event)
        except RuntimeError:
            return False

    def clear_drop_indicator(self):
        if self._drop_indicator_item is None:
            return

        self._drop_indicator_item = None
        self._drop_indicator_draw_bottom = False
        try:
            self.widget.viewport().update()
        except RuntimeError:
            return

    def update_drop_indicator(self, pos):
        group_item, insert_row = self.resolve_drop_target_position(pos)
        if group_item is None:
            self.clear_drop_indicator()
            return

        indicator_item = None
        draw_bottom = False
        child_count = group_item.childCount()
        if child_count > 0:
            if insert_row >= child_count:
                indicator_item = group_item.child(child_count - 1)
                draw_bottom = True
            else:
                indicator_item = group_item.child(insert_row)
        else:
            indicator_item = group_item
            draw_bottom = True

        if indicator_item is self._drop_indicator_item and draw_bottom == self._drop_indicator_draw_bottom:
            return

        self._drop_indicator_item = indicator_item
        self._drop_indicator_draw_bottom = draw_bottom
        self.widget.viewport().update()

    def resolve_drop_target_position(self, pos):
        target_item = self.widget.itemAt(pos)
        if target_item is None:
            return None, 0

        kind = target_item.data(0, ROLE_KIND)
        if kind == 'group':
            group_item = target_item
            insert_row = group_item.childCount()
        elif kind in {'entry', 'separator'}:
            group_item = target_item.parent()
            if group_item is None:
                return None, 0

            row = group_item.indexOfChild(target_item)
            rect = self.widget.visualItemRect(target_item)
            insert_row = row if pos.y() < rect.center().y() else row + 1
        else:
            return None, 0

        group_name = str(group_item.data(0, ROLE_GROUP_NAME) or group_item.text(0) or '').strip()
        if group_name not in self.allowed_drop_groups:
            return None, 0

        return group_item, max(0, insert_row)

    def can_handle_external_folder_drop(self, event):
        paths = self.extract_local_directory_paths(event)
        if not paths:
            return False

        target_group, _ = self.resolve_drop_target_position(event.position().toPoint())
        return target_group is not None

    def handle_external_folder_drop(self, event):
        paths = self.extract_local_directory_paths(event)
        if not paths:
            return False

        target_group, insert_row = self.resolve_drop_target_position(event.position().toPoint())
        if target_group is None:
            return False

        inserted = self.insert_paths_into_group(target_group, paths, insert_row=insert_row)
        if not inserted:
            event.ignore()
            return True

        target_group.setExpanded(True)
        self.save_current_state()
        event.acceptProposedAction()
        return True

    def resolve_drop_target_group(self, pos):
        group_item, _ = self.resolve_drop_target_position(pos)
        return group_item

    def extract_local_directory_paths(self, event):
        mime_data = event.mimeData()
        if mime_data is None or not mime_data.hasUrls():
            return []

        seen = set()
        directories = []
        for url in mime_data.urls():
            if not url.isLocalFile():
                continue

            local_path = os.path.normpath(os.path.expanduser(url.toLocalFile()))
            if not os.path.isdir(local_path):
                continue
            if local_path in seen:
                continue

            seen.add(local_path)
            directories.append(local_path)

        return directories

    def insert_paths_into_group(self, group_item, paths, insert_row=None):
        existing_paths = set()
        for child_index in range(group_item.childCount()):
            child = group_item.child(child_index)
            if child.data(0, ROLE_KIND) != 'entry':
                continue
            entry_path = child.data(0, ROLE_PATH)
            if entry_path:
                existing_paths.add(os.path.normpath(str(entry_path)))

        inserted = False
        row_cursor = group_item.childCount() if insert_row is None else max(0, min(int(insert_row), group_item.childCount()))
        for path in paths:
            normalized_path = os.path.normpath(path)
            if normalized_path in existing_paths:
                continue

            label = Path(normalized_path).name or normalized_path
            item = QTreeWidgetItem([label])
            item.setData(0, ROLE_KIND, 'entry')
            item.setData(0, ROLE_PATH, normalized_path)
            item.setData(0, ROLE_ICON, 'folder')
            item.setData(0, ROLE_ENTRY_TYPE, 'entry')
            item.setData(0, ROLE_ENTRY_DYNAMIC, '')
            item.setData(0, ROLE_ENTRY_KEY, f'entry:drop:{normalized_path}')
            item.setData(0, ROLE_ENTRY_SOURCE, 'custom')

            flags = item.flags()
            flags |= Qt.ItemFlag.ItemIsDragEnabled
            flags &= ~Qt.ItemFlag.ItemIsDropEnabled
            item.setFlags(flags)

            entry_icon = self.resolve_icon('folder', QStyle.StandardPixmap.SP_DirIcon)
            if not entry_icon.isNull():
                item.setIcon(0, entry_icon)

            group_item.insertChild(row_cursor, item)
            existing_paths.add(normalized_path)
            inserted = True
            row_cursor += 1

        return inserted

    def load_data(self):
        if not self.data_path.exists():
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
            default_data = copy.deepcopy(DEFAULT_NAVIGATOR_DATA)
            self.save_data(default_data)
            return default_data

        try:
            with self.data_path.open('r', encoding='utf-8') as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError):
            data = copy.deepcopy(DEFAULT_NAVIGATOR_DATA)

        groups = data.get('groups') if isinstance(data, dict) else None
        if not isinstance(groups, list):
            data = copy.deepcopy(DEFAULT_NAVIGATOR_DATA)

        return data

    def save_data(self, data):
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        with self.data_path.open('w', encoding='utf-8') as file:
            json.dump(data, file, ensure_ascii=False, indent=2)

    def build_from_data(self, data):
        rendered_groups = 0
        for group in data.get('groups', []):
            is_active = group.get('active', True)
            if not is_active:
                continue

            if rendered_groups > 0:
                spacer_item = QTreeWidgetItem([""])
                spacer_item.setData(0, ROLE_KIND, 'group-spacer')
                spacer_item.setFlags(Qt.ItemFlag.NoItemFlags)
                spacer_item.setSizeHint(0, QSize(0, 6))
                self.widget.addTopLevelItem(spacer_item)

            group_name = group.get('name', 'Gruppe')
            group_item = QTreeWidgetItem([group_name])
            group_item.setData(0, ROLE_KIND, 'group')
            group_item.setData(0, ROLE_GROUP_NAME, group_name)
            group_item.setData(0, ROLE_ICON, group.get('icon', ''))
            group_item.setData(0, ROLE_COLLAPSIBLE, bool(group.get('collapsible', True)))
            group_item.setData(0, ROLE_DYNAMIC, group.get('dynamic', ''))
            group_flags = group_item.flags()
            group_flags &= ~Qt.ItemFlag.ItemIsSelectable
            group_flags &= ~Qt.ItemFlag.ItemIsDragEnabled
            group_flags |= Qt.ItemFlag.ItemIsDropEnabled
            group_item.setFlags(group_flags)

            group_font = group_item.font(0)
            group_font.setBold(True)
            group_item.setFont(0, group_font)
            group_item.setBackground(0, self.widget.palette().base().color().lighter(104))

            group_icon = self.resolve_icon(group.get('icon'), QStyle.StandardPixmap.SP_DirIcon)
            if not group_icon.isNull():
                group_item.setIcon(0, group_icon)

            dynamic_mode = group.get('dynamic', '')
            if dynamic_mode == 'system-drives':
                entries = self.get_system_drive_entries()
            else:
                entries = group.get('entries', [])

            show_orte_separator = True
            if str(group_name).strip() == 'Orte':
                show_orte_separator = self.has_active_system_entries(entries)

            for entry_index, entry in enumerate(entries):
                entry_type = entry.get('type', 'entry')
                entry_key = self.build_entry_key(entry, entry_index)

                if entry_type == 'separator':
                    separator_label = entry.get('label', '────────────')
                    separator_item = QTreeWidgetItem([separator_label])
                    separator_item.setData(0, ROLE_KIND, 'separator')
                    separator_item.setData(0, ROLE_ENTRY_TYPE, 'separator')
                    separator_item.setData(0, ROLE_ENTRY_KEY, entry_key)
                    separator_flags = separator_item.flags()
                    separator_flags |= Qt.ItemFlag.ItemIsSelectable
                    separator_flags |= Qt.ItemFlag.ItemIsDragEnabled
                    separator_flags &= ~Qt.ItemFlag.ItemIsDropEnabled
                    separator_item.setFlags(separator_flags)
                    if str(group_name).strip() == 'Orte':
                        separator_item.setHidden(not show_orte_separator)
                    group_item.addChild(separator_item)
                    continue

                if not entry.get('active', True):
                    continue

                resolved_entry = self.resolve_entry_data(entry)
                if not resolved_entry:
                    continue

                label = resolved_entry.get('label', 'Eintrag')
                path = os.path.expanduser(resolved_entry.get('path', ''))
                entry_item = QTreeWidgetItem([label])
                entry_item.setData(0, ROLE_KIND, 'entry')
                entry_item.setData(0, ROLE_PATH, path)
                entry_item.setData(0, ROLE_ICON, resolved_entry.get('icon', ''))
                entry_item.setData(0, ROLE_ENTRY_TYPE, 'entry')
                entry_item.setData(0, ROLE_ENTRY_DYNAMIC, resolved_entry.get('dynamic', ''))
                entry_item.setData(0, ROLE_ENTRY_KEY, entry_key)
                entry_item.setData(0, ROLE_ENTRY_SOURCE, resolved_entry.get('source', 'system'))
                entry_flags = entry_item.flags()
                entry_flags |= Qt.ItemFlag.ItemIsDragEnabled
                entry_flags &= ~Qt.ItemFlag.ItemIsDropEnabled
                entry_item.setFlags(entry_flags)

                entry_icon = self.resolve_icon(resolved_entry.get('icon'), QStyle.StandardPixmap.SP_FileIcon)
                if not entry_icon.isNull():
                    entry_item.setIcon(0, entry_icon)

                group_item.addChild(entry_item)

            collapsible = bool(group.get('collapsible', True))
            self.widget.addTopLevelItem(group_item)
            group_row = self.widget.indexOfTopLevelItem(group_item)
            self.widget.setFirstColumnSpanned(group_row, QModelIndex(), True)
            group_item.setExpanded(group.get('expanded', True) if collapsible else True)
            rendered_groups += 1

    def has_active_system_entries(self, entries):
        if not isinstance(entries, list):
            return False

        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if entry.get('type') == 'separator':
                continue

            source = str(entry.get('source', 'system')).strip()
            if source != 'system':
                continue
            if entry.get('active', True):
                return True

        return False

    def resolve_icon(self, icon_name, fallback_standard_icon):
        if icon_name:
            icon = QIcon.fromTheme(icon_name)
            if not icon.isNull():
                return icon
        return QApplication.style().standardIcon(fallback_standard_icon)

    def serialize(self):
        visible_groups = {}
        for top_index in range(self.widget.topLevelItemCount()):
            group_item = self.widget.topLevelItem(top_index)
            if group_item.data(0, ROLE_KIND) != 'group':
                continue
            group_name = group_item.data(0, ROLE_GROUP_NAME) or group_item.text(0)
            dynamic_mode = group_item.data(0, ROLE_DYNAMIC) or ""
            group_data = {
                "name": group_name,
                "active": True,
                "collapsible": bool(group_item.data(0, ROLE_COLLAPSIBLE)),
                "expanded": group_item.isExpanded(),
            }
            if dynamic_mode:
                group_data["dynamic"] = dynamic_mode
            else:
                group_data["entries"] = []

            group_icon = group_item.data(0, ROLE_ICON)
            if group_icon:
                group_data["icon"] = group_icon

            if not dynamic_mode:
                for child_index in range(group_item.childCount()):
                    child = group_item.child(child_index)
                    entry_type = child.data(0, ROLE_ENTRY_TYPE) or 'entry'
                    if entry_type == 'separator':
                        entry_data = {
                            "type": "separator",
                            "label": child.text(0),
                            "_entry_key": child.data(0, ROLE_ENTRY_KEY),
                        }
                    else:
                        entry_data = {
                            "label": child.text(0),
                            "active": True,
                            "_entry_key": child.data(0, ROLE_ENTRY_KEY),
                        }
                        entry_source = child.data(0, ROLE_ENTRY_SOURCE) or 'system'
                        if entry_source == 'custom':
                            entry_data["source"] = "custom"

                        entry_dynamic = child.data(0, ROLE_ENTRY_DYNAMIC)
                        if entry_dynamic:
                            entry_data["dynamic"] = entry_dynamic
                        else:
                            entry_data["path"] = child.data(0, ROLE_PATH) or ""

                        entry_icon = child.data(0, ROLE_ICON)
                        if entry_icon:
                            entry_data["icon"] = entry_icon

                    group_data["entries"].append(entry_data)

            visible_groups[group_name] = group_data

        groups = []
        for source_group in self.loaded_data.get('groups', []):
            source_name = source_group.get('name', 'Gruppe')
            if source_name in visible_groups:
                visible_group = visible_groups[source_name]
                if 'entries' in visible_group:
                    source_entries = source_group.get('entries', [])
                    visible_group['entries'] = self.merge_group_entries(source_entries, visible_group['entries'])
                groups.append(visible_group)
            else:
                hidden_group = copy.deepcopy(source_group)
                hidden_group['active'] = bool(source_group.get('active', False))
                groups.append(hidden_group)

        return {"groups": groups}

    def save_current_state(self):
        self.save_data(self.serialize())

    def on_context_menu_requested(self, pos):
        item = self.widget.itemAt(pos)
        if item is None:
            return

        if self.is_in_dynamic_group(item):
            return

        kind = item.data(0, ROLE_KIND)
        menu = QMenu(self.widget)

        if kind == 'entry' and (item.data(0, ROLE_ENTRY_TYPE) or 'entry') == 'entry':
            source = str(item.data(0, ROLE_ENTRY_SOURCE) or 'system').strip()
            if source == 'custom':
                rename_action = menu.addAction(
                    self.resolve_icon('edit-rename', QStyle.StandardPixmap.SP_FileDialogDetailedView),
                    'Umbenennen',
                )
                delete_action = menu.addAction(
                    self.resolve_icon('edit-delete', QStyle.StandardPixmap.SP_TrashIcon),
                    'Löschen',
                )
                chosen = menu.exec(self.widget.viewport().mapToGlobal(pos))
                if chosen == rename_action:
                    self.rename_custom_entry(item)
                if chosen == delete_action:
                    self.delete_custom_entry(item)
                return

            hide_action = menu.addAction(
                self.resolve_icon('list-remove', QStyle.StandardPixmap.SP_DialogCancelButton),
                'Ausblenden',
            )
            chosen = menu.exec(self.widget.viewport().mapToGlobal(pos))
            if chosen == hide_action:
                self.set_system_entry_active(item, False)
            return

        if kind == 'group':
            group_name = str(item.data(0, ROLE_GROUP_NAME) or item.text(0) or '').strip()
            inactive_entries = self.get_inactive_system_entries(group_name)
            if not inactive_entries:
                return

            activate_submenu = menu.addMenu('Einblenden')
            activate_submenu.setStyleSheet(
                "QMenu::separator {"
                "height: 1px;"
                "background: rgba(120, 120, 120, 180);"
                "margin: 4px 8px;"
                "}"
            )
            activate_actions = {}
            show_all_action = None
            if group_name == 'Orte':
                show_all_action = activate_submenu.addAction(
                    self.resolve_icon('view-visible', QStyle.StandardPixmap.SP_DialogApplyButton),
                    'Alle einblenden',
                )
                activate_submenu.addSeparator()
            for entry in inactive_entries:
                action = activate_submenu.addAction(
                    self.resolve_icon(entry.get('icon', ''), QStyle.StandardPixmap.SP_DirIcon),
                    entry['label'],
                )
                activate_actions[action] = entry['key']

            chosen = menu.exec(self.widget.viewport().mapToGlobal(pos))
            if show_all_action is not None and chosen == show_all_action:
                self.set_multiple_system_entries_active_by_keys(
                    group_name,
                    [entry['key'] for entry in inactive_entries],
                    True,
                )
                return
            if chosen in activate_actions:
                self.set_system_entry_active_by_key(group_name, activate_actions[chosen], True)

    def is_in_dynamic_group(self, item):
        kind = item.data(0, ROLE_KIND)
        if kind == 'group':
            group_item = item
        elif kind in {'entry', 'separator'}:
            group_item = item.parent()
        else:
            group_item = None

        if group_item is None:
            return False

        dynamic_mode = str(group_item.data(0, ROLE_DYNAMIC) or '').strip()
        return bool(dynamic_mode)

    def delete_custom_entry(self, item):
        parent = item.parent()
        if parent is None:
            return
        index = parent.indexOfChild(item)
        if index < 0:
            return

        parent.takeChild(index)
        self.save_current_state()
        self.loaded_data = self.load_data()

    def rename_custom_entry(self, item):
        current_name = (item.text(0) or '').strip() or 'Favorit'

        dialog = QInputDialog(self.widget)
        dialog.setWindowTitle('Favorit umbenennen')
        dialog.setLabelText('Name:')
        dialog.setTextValue(current_name)
        dialog.setTextEchoMode(QLineEdit.EchoMode.Normal)
        dialog.setMinimumWidth(520)

        if dialog.exec() != QInputDialog.DialogCode.Accepted:
            return

        new_name = dialog.textValue().strip()
        if not new_name:
            return

        item.setText(0, new_name)
        self.save_current_state()
        self.loaded_data = self.load_data()

    def set_system_entry_active(self, item, active):
        parent = item.parent()
        if parent is None:
            return

        group_name = str(parent.data(0, ROLE_GROUP_NAME) or parent.text(0) or '').strip()
        entry_key = item.data(0, ROLE_ENTRY_KEY)
        if not group_name or not entry_key:
            return

        self.set_system_entry_active_by_key(group_name, str(entry_key), bool(active))

    def set_system_entry_active_by_key(self, group_name, entry_key, active):
        groups = self.loaded_data.get('groups', []) if isinstance(self.loaded_data, dict) else []
        for group in groups:
            if str(group.get('name', '')).strip() != group_name:
                continue

            entries = group.get('entries', [])
            if not isinstance(entries, list):
                return

            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue

                source = str(entry.get('source', 'system')).strip()
                if source != 'system':
                    continue

                key = self.build_entry_key(entry, idx)
                if key != entry_key:
                    continue

                entry['active'] = bool(active)
                self.save_data(self.loaded_data)
                self.loaded_data = self.load_data()
                self.widget.clear()
                self.build_from_data(self.loaded_data)
                return

    def set_multiple_system_entries_active_by_keys(self, group_name, entry_keys, active):
        keys = set(str(key) for key in entry_keys if key)
        if not keys:
            return

        groups = self.loaded_data.get('groups', []) if isinstance(self.loaded_data, dict) else []
        changed = False
        for group in groups:
            if str(group.get('name', '')).strip() != group_name:
                continue

            entries = group.get('entries', [])
            if not isinstance(entries, list):
                break

            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue

                source = str(entry.get('source', 'system')).strip()
                if source != 'system':
                    continue

                key = self.build_entry_key(entry, idx)
                if key not in keys:
                    continue

                entry['active'] = bool(active)
                changed = True
            break

        if not changed:
            return

        self.save_data(self.loaded_data)
        self.loaded_data = self.load_data()
        self.widget.clear()
        self.build_from_data(self.loaded_data)

    def get_inactive_system_entries(self, group_name):
        groups = self.loaded_data.get('groups', []) if isinstance(self.loaded_data, dict) else []
        for group in groups:
            if str(group.get('name', '')).strip() != group_name:
                continue

            entries = group.get('entries', [])
            if not isinstance(entries, list):
                return []

            result = []
            for idx, entry in enumerate(entries):
                if not isinstance(entry, dict):
                    continue
                if entry.get('type') == 'separator':
                    continue

                source = str(entry.get('source', 'system')).strip()
                if source != 'system':
                    continue
                if entry.get('active', True):
                    continue

                label = str(entry.get('label') or entry.get('dynamic') or 'Eintrag')
                result.append(
                    {
                        'label': label,
                        'key': self.build_entry_key(entry, idx),
                        'icon': entry.get('icon', ''),
                    }
                )
            return result

        return []

    def get_entry_path(self, item: QTreeWidgetItem):
        if item.data(0, ROLE_KIND) != 'entry':
            return None
        path = item.data(0, ROLE_PATH)
        if not path:
            return None
        return path

    def on_item_collapsed(self, item: QTreeWidgetItem):
        if item.data(0, ROLE_KIND) != 'group':
            return
        if not bool(item.data(0, ROLE_COLLAPSIBLE)):
            item.setExpanded(True)

    def resolve_entry_data(self, entry):
        dynamic_token = entry.get('dynamic', '')
        if not dynamic_token:
            return entry

        dynamic_entry = {
            'dynamic': dynamic_token,
            'label': entry.get('label', ''),
            'icon': entry.get('icon', ''),
        }

        if dynamic_token == 'home':
            dynamic_entry['path'] = os.path.expanduser('~')
            dynamic_entry['label'] = dynamic_entry['label'] or 'Persönlicher Ordner'
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'user-home'
        elif dynamic_token == 'trash':
            dynamic_entry['path'] = os.path.expanduser('~/.local/share/Trash/files')
            dynamic_entry['label'] = dynamic_entry['label'] or 'Papierkorb'
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'user-trash'
        elif dynamic_token == 'desktop':
            desktop_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
            dynamic_entry['path'] = desktop_path or os.path.expanduser('~/Desktop')
            dynamic_entry['label'] = dynamic_entry['label'] or 'Arbeitsfläche'
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'user-desktop'
        elif dynamic_token == 'documents':
            documents_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            dynamic_entry['path'] = documents_path or os.path.expanduser('~/Documents')
            dynamic_entry['label'] = dynamic_entry['label'] or 'Dokumente'
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'folder-documents'
        elif dynamic_token == 'downloads':
            downloads_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            dynamic_entry['path'] = downloads_path or os.path.expanduser('~/Downloads')
            dynamic_entry['label'] = dynamic_entry['label'] or 'Downloads'
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'folder-download'
        else:
            return entry

        return dynamic_entry

    def build_entry_key(self, entry, entry_index):
        entry_type = entry.get('type', 'entry')
        if entry_type == 'separator':
            return entry.get('id', f'separator:{entry_index}')

        dynamic_token = entry.get('dynamic', '')
        if dynamic_token:
            return f'dynamic:{dynamic_token}'

        label = entry.get('label', '')
        path = entry.get('path', '')
        return f'entry:{entry_index}:{label}:{path}'

    def merge_group_entries(self, source_entries, visible_entries):
        source_map = {}
        for source_index, source_entry in enumerate(source_entries):
            key = self.build_entry_key(source_entry, source_index)
            source_map[key] = copy.deepcopy(source_entry)

        hidden_entries = []
        for source_index, source_entry in enumerate(source_entries):
            key = self.build_entry_key(source_entry, source_index)
            if source_entry.get('type') == 'separator':
                continue
            if not source_entry.get('active', True):
                hidden_entries.append(copy.deepcopy(source_entry))

        merged_entries = []
        for visible_entry in visible_entries:
            normalized_visible = copy.deepcopy(visible_entry)
            entry_key = normalized_visible.pop('_entry_key', None)

            if normalized_visible.get('type') == 'separator':
                normalized_visible.pop('active', None)

            if entry_key and entry_key in source_map:
                source_entry = source_map[entry_key]
                if source_entry.get('type') == 'separator':
                    normalized_visible.pop('active', None)
                merged_entries.append(normalized_visible)
            else:
                merged_entries.append(normalized_visible)

        merged_entries.extend(hidden_entries)

        return merged_entries

    def get_system_drive_entries(self):
        drive_paths = []
        seen_paths = set()

        def iter_subdirs(path_obj):
            try:
                for child in path_obj.iterdir():
                    try:
                        if child.is_dir():
                            yield child
                    except OSError:
                        continue
            except OSError:
                return

        def add_path(path):
            expanded_path = os.path.expanduser(path)
            if not os.path.isdir(expanded_path):
                return
            normalized = os.path.normpath(expanded_path)
            if normalized in seen_paths:
                return
            seen_paths.add(normalized)
            drive_paths.append(normalized)

        add_path('/')

        for base in ['/mnt', '/media']:
            base_path = Path(base)
            if base_path.is_dir():
                for entry in sorted(iter_subdirs(base_path)):
                    add_path(str(entry))

        run_media_base = Path('/run/media')
        if run_media_base.is_dir():
            for user_dir in sorted(iter_subdirs(run_media_base)):
                for mount_dir in sorted(iter_subdirs(user_dir)):
                    add_path(str(mount_dir))

        entries = []
        for path in drive_paths:
            label = 'Root' if path == '/' else Path(path).name
            entries.append({
                'label': label,
                'path': path,
                'icon': 'drive-harddisk',
            })

        return entries
