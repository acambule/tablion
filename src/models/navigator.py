import copy
import json
import os
from pathlib import Path

from PySide6.QtCore import Qt, QModelIndex, QStandardPaths, QEvent, QObject, QSize, Signal, QRect
from PySide6.QtGui import QColor, QIcon, QPen
from PySide6.QtWidgets import QApplication, QAbstractItemView, QHeaderView, QStyle, QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QMenu, QInputDialog, QLineEdit, QWidgetAction, QCheckBox

from localization import app_tr
from domain.filesystem import PaneLocation


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
ROLE_LOCATION_KIND = Qt.ItemDataRole.UserRole + 10
ROLE_REMOTE_ID = Qt.ItemDataRole.UserRole + 11


DEFAULT_NAVIGATOR_DATA = {
    "groups": [
        {
            "name": "Places",
            "active": True,
            "collapsible": False,
            "expanded": True,
            "icon": "folder-favorites",
            "entries": [
                {"label": "Home", "dynamic": "home", "icon": "user-home", "active": True},
                {"label": "Trash", "dynamic": "trash", "icon": "user-trash", "active": True},
                {"label": "Desktop", "dynamic": "desktop", "icon": "user-desktop", "active": True},
                {"label": "Documents", "dynamic": "documents", "icon": "folder-documents", "active": True},
                {"label": "Downloads", "dynamic": "downloads", "icon": "folder-download", "active": True},
            ],
        },
        {
            "name": "Cloud",
            "active": True,
            "collapsible": True,
            "expanded": True,
            "icon": "folder-cloud",
            "entries": [],
        },
        {
            "name": "Drives",
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

        current_item = self.manager.widget.itemFromIndex(index)
        if current_item is not None:
            self.manager.paint_group_action_icon(painter, option, current_item)

        indicator_item = self.manager._drop_indicator_item
        if indicator_item is None:
            return

        if current_item is not indicator_item:
            return

        rect = option.rect
        y = rect.bottom() if self.manager._drop_indicator_draw_bottom else rect.top()

        painter.save()
        painter.setPen(QPen(QColor(110, 110, 110, 210), 2))
        painter.drawLine(rect.left() + 8, y, rect.right() - 8, y)
        painter.restore()


class NavigatorManager(QObject):
    entryMiddleClicked = Signal(object)
    remoteMountEditRequested = Signal(str)
    remoteCloudSettingsRequested = Signal()

    def __init__(self, widget: QTreeWidget, data_path: Path, remote_mount_settings=None, remote_connection_settings=None):
        super().__init__(widget)
        self.widget = widget
        self.data_path = data_path
        self.remote_mount_settings = remote_mount_settings
        self.remote_connection_settings = remote_connection_settings
        self.loaded_data = {"groups": []}
        self.allowed_drop_groups = {"Places", "Cloud"}
        self._drop_indicator_item = None
        self._drop_indicator_draw_bottom = False

    def _normalize_group_name(self, name: str) -> str:
        text = str(name or "").strip().lower()
        mapping = {
            "places": "Places",
            "orte": "Places",
            "cloud": "Cloud",
            "drives": "Drives",
            "laufwerke": "Drives",
        }
        return mapping.get(text, str(name or "").strip())

    def _canonical_system_label(self, dynamic_token: str, raw_label: str) -> str:
        token = str(dynamic_token or "").strip().lower()
        if token == "home":
            return "Home"
        if token == "trash":
            return "Trash"
        if token == "desktop":
            return "Desktop"
        if token == "documents":
            return "Documents"
        if token == "downloads":
            return "Downloads"

        text = str(raw_label or "").strip().lower()
        mapping = {
            "persönlicher ordner": "Home",
            "papierkorb": "Trash",
            "arbeitsfläche": "Desktop",
            "dokumente": "Documents",
            "downloads": "Downloads",
        }
        return mapping.get(text, str(raw_label or "").strip())

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
                if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
                    if self.handle_group_action_click(event.position().toPoint()):
                        return True

                if event.type() == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.MiddleButton:
                    item = self.widget.itemAt(event.position().toPoint())
                    location = self.get_entry_location(item) if item is not None else None
                    if location is not None:
                        self.entryMiddleClicked.emit(location)
                        return True

                if event.type() == QEvent.Type.DragEnter:
                    if self.can_handle_internal_custom_drop(event):
                        self.update_drop_indicator(event.position().toPoint())
                        event.acceptProposedAction()
                        return True
                    if self.can_handle_external_folder_drop(event):
                        self.update_drop_indicator(event.position().toPoint())
                        event.acceptProposedAction()
                        return True

                if event.type() == QEvent.Type.DragMove:
                    if self.can_handle_internal_custom_drop(event):
                        self.update_drop_indicator(event.position().toPoint())
                        event.acceptProposedAction()
                        return True
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
                        if self.handle_internal_custom_drop(event):
                            return True
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

        group_name = self._normalize_group_name(group_item.data(0, ROLE_GROUP_NAME) or group_item.text(0) or '')
        if group_name not in self.allowed_drop_groups:
            return None, 0

        return group_item, max(0, insert_row)

    def can_handle_external_folder_drop(self, event):
        paths = self.extract_local_directory_paths(event)
        if not paths:
            return False

        target_group, _ = self.resolve_drop_target_position(event.position().toPoint())
        return target_group is not None

    def can_handle_internal_custom_drop(self, event):
        if event.source() is not self.widget:
            return False
        dragged_items = self._selected_custom_drag_items()
        if not dragged_items:
            return False

        target_group, insert_row = self.resolve_drop_target_position(event.position().toPoint())
        if target_group is None:
            return False

        source_group = dragged_items[0].parent()
        if source_group is None or target_group is not source_group:
            return False

        minimum_row = self._minimum_custom_insert_row(source_group)
        return insert_row >= minimum_row

    def handle_internal_custom_drop(self, event):
        if event.source() is not self.widget:
            return False
        dragged_items = self._selected_custom_drag_items()
        if not dragged_items:
            return False

        target_group, insert_row = self.resolve_drop_target_position(event.position().toPoint())
        if target_group is None:
            return False

        source_group = dragged_items[0].parent()
        if source_group is None or target_group is not source_group:
            event.ignore()
            return True

        minimum_row = self._minimum_custom_insert_row(source_group)
        if insert_row < minimum_row:
            event.ignore()
            return True

        dragged_paths = [os.path.normpath(str(item.data(0, ROLE_PATH))) for item in dragged_items if item.data(0, ROLE_PATH)]
        if not dragged_paths:
            event.ignore()
            return True

        custom_insert_index = 0
        for row in range(0, min(insert_row, target_group.childCount())):
            child = target_group.child(row)
            if child.data(0, ROLE_KIND) != 'entry':
                continue
            if str(child.data(0, ROLE_ENTRY_SOURCE) or 'system').strip() != 'custom':
                continue
            child_path = child.data(0, ROLE_PATH)
            if child_path and os.path.normpath(str(child_path)) in dragged_paths:
                continue
            custom_insert_index += 1

        if not self._reorder_custom_entries_in_group(target_group, dragged_paths, custom_insert_index):
            event.ignore()
            return True

        group_name = self._normalize_group_name(target_group.data(0, ROLE_GROUP_NAME) or target_group.text(0) or '')
        self.loaded_data = self.load_data()
        self.widget.clear()
        self.build_from_data(self.loaded_data)
        self._expand_group_by_name(group_name)
        event.acceptProposedAction()
        return True

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

        group_name = self._normalize_group_name(target_group.data(0, ROLE_GROUP_NAME) or target_group.text(0) or '')
        target_group.setExpanded(True)
        self.save_current_state()
        self.loaded_data = self.load_data()
        self.widget.clear()
        self.build_from_data(self.loaded_data)
        if group_name:
            for top_index in range(self.widget.topLevelItemCount()):
                candidate = self.widget.topLevelItem(top_index)
                candidate_name = self._normalize_group_name(candidate.data(0, ROLE_GROUP_NAME) or candidate.text(0) or '')
                if candidate_name == group_name:
                    candidate.setExpanded(True)
                    break
        event.acceptProposedAction()
        return True

    def resolve_drop_target_group(self, pos):
        group_item, _ = self.resolve_drop_target_position(pos)
        return group_item

    def _selected_custom_drag_items(self):
        selected_items = list(self.widget.selectedItems())
        if not selected_items:
            return []

        custom_items = []
        group_item = None
        for item in selected_items:
            if item.data(0, ROLE_KIND) != 'entry':
                return []
            if str(item.data(0, ROLE_ENTRY_SOURCE) or 'system').strip() != 'custom':
                return []
            parent = item.parent()
            if parent is None:
                return []
            if group_item is None:
                group_item = parent
            elif parent is not group_item:
                return []
            custom_items.append(item)
        return custom_items

    def _minimum_custom_insert_row(self, group_item):
        if group_item is None:
            return 0
        group_name = self._normalize_group_name(group_item.data(0, ROLE_GROUP_NAME) or group_item.text(0) or '')
        if group_name != 'Places':
            return 0

        for row in range(group_item.childCount()):
            child = group_item.child(row)
            if child.data(0, ROLE_KIND) == 'separator':
                return row + 1
            if child.data(0, ROLE_KIND) == 'entry' and str(child.data(0, ROLE_ENTRY_SOURCE) or 'system').strip() == 'custom':
                return row
        return group_item.childCount()

    def _reorder_custom_entries_in_group(self, group_item, dragged_paths, custom_insert_index):
        group_name = self._normalize_group_name(group_item.data(0, ROLE_GROUP_NAME) or group_item.text(0) or '')
        groups = self.loaded_data.get('groups', []) if isinstance(self.loaded_data, dict) else []
        target_group = next((group for group in groups if self._normalize_group_name(group.get('name', '')) == group_name), None)
        if not isinstance(target_group, dict):
            return False

        entries = target_group.get('entries', [])
        if not isinstance(entries, list):
            return False

        system_entries = []
        custom_entries = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            if str(entry.get('source', 'system')).strip() == 'custom':
                custom_entries.append(copy.deepcopy(entry))
            else:
                system_entries.append(copy.deepcopy(entry))

        moving_entries = []
        remaining_entries = []
        dragged_path_set = set(dragged_paths)
        for entry in custom_entries:
            entry_path = os.path.normpath(os.path.expanduser(str(entry.get('path') or '')))
            if entry_path in dragged_path_set:
                moving_entries.append(entry)
            else:
                remaining_entries.append(entry)

        if not moving_entries:
            return False

        insert_index = max(0, min(custom_insert_index, len(remaining_entries)))
        reordered_custom_entries = list(remaining_entries)
        reordered_custom_entries[insert_index:insert_index] = moving_entries
        target_group['entries'] = system_entries + reordered_custom_entries
        self.save_data(self.loaded_data)
        return True

    def _expand_group_by_name(self, group_name):
        if not group_name:
            return
        for top_index in range(self.widget.topLevelItemCount()):
            candidate = self.widget.topLevelItem(top_index)
            candidate_name = self._normalize_group_name(candidate.data(0, ROLE_GROUP_NAME) or candidate.text(0) or '')
            if candidate_name == group_name:
                candidate.setExpanded(True)
                return

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
            try:
                if not os.path.isdir(local_path):
                    continue
            except (OSError, PermissionError):
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
            try:
                self.data_path.parent.mkdir(parents=True, exist_ok=True)
            except (OSError, PermissionError):
                pass
            default_data = copy.deepcopy(DEFAULT_NAVIGATOR_DATA)
            try:
                self.save_data(default_data)
            except Exception:
                pass
            return default_data

        try:
            with self.data_path.open('r', encoding='utf-8') as file:
                data = json.load(file)
        except (json.JSONDecodeError, OSError, PermissionError):
            data = copy.deepcopy(DEFAULT_NAVIGATOR_DATA)

        groups = data.get('groups') if isinstance(data, dict) else None
        if not isinstance(groups, list):
            data = copy.deepcopy(DEFAULT_NAVIGATOR_DATA)

        return data


    def save_data(self, data):
        try:
            self.data_path.parent.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError):
            return
        try:
            with self.data_path.open('w', encoding='utf-8') as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
        except (OSError, PermissionError):
            pass

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

            raw_group_name = group.get('name', 'Gruppe')
            canonical_group_name = self._normalize_group_name(raw_group_name)
            group_name = app_tr('NavigatorManager', canonical_group_name)
            group_item = QTreeWidgetItem([group_name])
            group_item.setData(0, ROLE_KIND, 'group')
            group_item.setData(0, ROLE_GROUP_NAME, canonical_group_name)
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
            elif canonical_group_name == 'Places':
                entries = self._group_entries_with_system_defaults('Places')
            else:
                entries = group.get('entries', [])

            if canonical_group_name == 'Cloud':
                entries = list(entries) if isinstance(entries, list) else []
                entries.extend(self._remote_entries())

            if canonical_group_name == 'Places' and isinstance(entries, list):
                system_entries = []
                custom_entries = []
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get('type') == 'separator':
                        continue
                    source = str(entry.get('source', 'system')).strip()
                    if source == 'custom':
                        custom_entries.append(entry)
                    else:
                        system_entries.append(entry)

                visible_system_entries = [entry for entry in system_entries if entry.get('active', True)]
                visible_custom_entries = [entry for entry in custom_entries if entry.get('active', True)]

                entries = list(visible_system_entries)
                if visible_system_entries and visible_custom_entries:
                    entries.append({'type': 'separator', 'label': '────────────', 'id': 'separator:orte-custom'})
                entries.extend(visible_custom_entries)

            for entry_index, entry in enumerate(entries):
                entry_type = entry.get('type', 'entry')
                entry_key = self.build_entry_key(entry, entry_index)

                if entry_type == 'separator':
                    separator_label = entry.get('label', '────────────')
                    separator_item = QTreeWidgetItem([separator_label])
                    separator_item.setData(0, ROLE_KIND, 'separator')
                    separator_item.setData(0, ROLE_ENTRY_TYPE, 'separator')
                    separator_item.setData(0, ROLE_ENTRY_KEY, entry_key)
                    separator_item.setFlags(Qt.ItemFlag.NoItemFlags)
                    group_item.addChild(separator_item)
                    continue

                if not entry.get('active', True):
                    continue

                resolved_entry = self.resolve_entry_data(entry)
                if not resolved_entry:
                    continue

                raw_label = resolved_entry.get('label', '')
                dynamic_token = resolved_entry.get('dynamic', '')
                source = str(resolved_entry.get('source', 'system')).strip()
                if source == 'system':
                    effective_label = self._canonical_system_label(dynamic_token, raw_label)
                    label = app_tr('NavigatorManager', effective_label)
                else:
                    effective_label = str(raw_label or '').strip()
                    label = effective_label
                path = os.path.expanduser(resolved_entry.get('path', ''))
                entry_item = QTreeWidgetItem([label])
                entry_item.setData(0, ROLE_ENTRY_KEY, effective_label)
                entry_item.setData(0, ROLE_KIND, 'entry')
                entry_item.setData(0, ROLE_PATH, path)
                entry_item.setData(0, ROLE_ICON, resolved_entry.get('icon', ''))
                entry_item.setData(0, ROLE_ENTRY_TYPE, 'entry')
                entry_item.setData(0, ROLE_ENTRY_DYNAMIC, resolved_entry.get('dynamic', ''))
                entry_item.setData(0, ROLE_ENTRY_SOURCE, resolved_entry.get('source', 'system'))
                entry_item.setData(0, ROLE_LOCATION_KIND, resolved_entry.get('location_kind', 'local'))
                entry_item.setData(0, ROLE_REMOTE_ID, resolved_entry.get('remote_id', ''))
                tooltip = str(resolved_entry.get('tooltip') or '').strip()
                if tooltip:
                    entry_item.setToolTip(0, tooltip)
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

    def retranslate(self):
        """Reapply translations to all navigator items."""
        for top in range(self.widget.topLevelItemCount()):
            group_item = self.widget.topLevelItem(top)
            raw_group = group_item.data(0, ROLE_GROUP_NAME)
            if isinstance(raw_group, str) and raw_group:
                group_item.setText(0, app_tr('NavigatorManager', raw_group))
            for child_idx in range(group_item.childCount()):
                child = group_item.child(child_idx)
                if child.data(0, ROLE_KIND) != 'entry':
                    continue
                source = str(child.data(0, ROLE_ENTRY_SOURCE) or 'system').strip()
                raw_label = child.data(0, ROLE_ENTRY_KEY)
                if source == 'system' and isinstance(raw_label, str) and raw_label:
                    child.setText(0, app_tr('NavigatorManager', raw_label))

    def resolve_icon(self, icon_name, fallback_standard_icon):
        if icon_name:
            icon_text = str(icon_name).strip()
            if icon_text:
                icon_path = Path(icon_text).expanduser()
                if icon_path.exists() and icon_path.is_file():
                    icon = QIcon(str(icon_path))
                    if not icon.isNull():
                        return icon

                icon = QIcon.fromTheme(icon_text)
                if not icon.isNull():
                    return icon
        return QApplication.style().standardIcon(fallback_standard_icon)

    def serialize(self):
        visible_groups = {}
        for top_index in range(self.widget.topLevelItemCount()):
            group_item = self.widget.topLevelItem(top_index)
            if group_item.data(0, ROLE_KIND) != 'group':
                continue
            group_name = self._normalize_group_name(group_item.data(0, ROLE_GROUP_NAME) or group_item.text(0))
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
                        if entry_source == 'remote':
                            continue
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

            visible_groups[self._normalize_group_name(group_name)] = group_data

        groups = []
        for source_group in self.loaded_data.get('groups', []):
            source_name = self._normalize_group_name(source_group.get('name', 'Gruppe'))
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
        item = self._context_menu_item_at(pos)
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
                    app_tr('NavigatorManager', 'Umbenennen'),
                )
                delete_action = menu.addAction(
                    self.resolve_icon('edit-delete', QStyle.StandardPixmap.SP_TrashIcon),
                    app_tr('NavigatorManager', 'Löschen'),
                )
                chosen = menu.exec(self.widget.viewport().mapToGlobal(pos))
                if chosen == rename_action:
                    self.rename_custom_entry(item)
                if chosen == delete_action:
                    self.delete_custom_entry(item)
                return
            if source == 'remote':
                edit_action = menu.addAction(
                    self.resolve_icon('document-edit', QStyle.StandardPixmap.SP_FileDialogDetailedView),
                    app_tr('NavigatorManager', 'Bearbeiten'),
                )
                chosen = menu.exec(self.widget.viewport().mapToGlobal(pos))
                if chosen == edit_action:
                    remote_id = str(item.data(0, ROLE_REMOTE_ID) or "").strip()
                    if remote_id:
                        self.remoteMountEditRequested.emit(remote_id)
                return

            hide_action = menu.addAction(
                self.resolve_icon('list-remove', QStyle.StandardPixmap.SP_DialogCancelButton),
                app_tr('NavigatorManager', 'Ausblenden'),
            )
            chosen = menu.exec(self.widget.viewport().mapToGlobal(pos))
            if chosen == hide_action:
                self.set_system_entry_active(item, False)
            return

        if kind == 'group':
            group_name = self._normalize_group_name(item.data(0, ROLE_GROUP_NAME) or item.text(0) or '')
            if group_name == 'Places':
                return
            inactive_entries = self.get_inactive_system_entries(group_name)
            if not inactive_entries:
                return

            activate_submenu = menu.addMenu(app_tr('NavigatorManager', 'Einblenden'))
            activate_submenu.setStyleSheet(
                "QMenu::separator {"
                "height: 1px;"
                "background: rgba(120, 120, 120, 180);"
                "margin: 4px 8px;"
                "}"
            )
            activate_actions = {}
            for entry in inactive_entries:
                action = activate_submenu.addAction(
                    self.resolve_icon(entry.get('icon', ''), QStyle.StandardPixmap.SP_DirIcon),
                    app_tr('NavigatorManager', self._canonical_system_label('', entry.get('label', ''))),
                )
                activate_actions[action] = entry['key']

            chosen = menu.exec(self.widget.viewport().mapToGlobal(pos))
            if chosen in activate_actions:
                self.set_system_entry_active_by_key(group_name, activate_actions[chosen], True)

    def paint_group_action_icon(self, painter, option, item):
        if not self.group_has_action_icon(item):
            return

        icon = self.resolve_icon('settings-configure', QStyle.StandardPixmap.SP_FileDialogDetailedView)
        if icon.isNull():
            return

        icon_rect = self.group_action_icon_rect(item)
        if not icon_rect.isValid():
            return
        if not option.rect.intersects(icon_rect):
            return

        icon.paint(painter, icon_rect)

    def group_has_action_icon(self, item):
        if item is None:
            return False
        if item.data(0, ROLE_KIND) != 'group':
            return False
        group_name = self._normalize_group_name(item.data(0, ROLE_GROUP_NAME) or item.text(0) or '')
        return group_name in {'Places', 'Cloud'}

    def group_action_icon_rect(self, item):
        if not self.group_has_action_icon(item):
            return self.widget.visualItemRect(item)

        rect = self.widget.visualItemRect(item)
        if not rect.isValid():
            return rect

        size = max(14, min(18, rect.height() - 6))
        margin = 8
        x = rect.right() - size - margin
        y = rect.top() + max(0, (rect.height() - size) // 2)
        return QRect(x, y, size, size)

    def handle_group_action_click(self, pos):
        item = self._context_menu_item_at(pos)
        if item is None or not self.group_has_action_icon(item):
            return False

        icon_rect = self.group_action_icon_rect(item)
        if not icon_rect.contains(pos):
            return False

        group_name = self._normalize_group_name(item.data(0, ROLE_GROUP_NAME) or item.text(0) or '')
        if group_name == 'Cloud':
            self.remoteCloudSettingsRequested.emit()
            return True

        menu = QMenu(self.widget)
        self.show_places_group_context_menu(menu, pos)
        return True

    def _context_menu_item_at(self, pos):
        item = self.widget.itemAt(pos)
        if item is not None:
            return item

        # Group rows are visually wider than the item's text hitbox. Resolve by row as fallback.
        for top_index in range(self.widget.topLevelItemCount()):
            top_item = self.widget.topLevelItem(top_index)
            for candidate in self._iter_item_rows(top_item):
                rect = self.widget.visualItemRect(candidate)
                if rect.isValid() and rect.top() <= pos.y() <= rect.bottom():
                    return candidate
        return None

    def _iter_item_rows(self, item):
        if item is None:
            return
        yield item
        for child_index in range(item.childCount()):
            child = item.child(child_index)
            yield from self._iter_item_rows(child)

    def show_places_group_context_menu(self, menu, pos):
        all_entries = self.get_all_system_entries("Places")
        if not all_entries:
            return False

        all_active = all(bool(entry.get('active', True)) for entry in all_entries)
        activate_all_action = menu.addAction(
            self.resolve_icon('view-visible', QStyle.StandardPixmap.SP_DialogApplyButton),
            app_tr('NavigatorManager', 'Alle ausblenden' if all_active else 'Alle einblenden'),
        )
        menu.addSeparator()

        for entry in all_entries:
            checkbox = QCheckBox(app_tr('NavigatorManager', self._canonical_system_label('', entry.get('label', ''))), menu)
            checkbox.setChecked(bool(entry.get('active', True)))
            checkbox.stateChanged.connect(
                lambda state, key=entry.get('key', ''): self.set_system_entry_active_by_key("Places", key, state == Qt.CheckState.Checked.value)
            )
            action = QWidgetAction(menu)
            action.setDefaultWidget(checkbox)
            menu.addAction(action)

        chosen = menu.exec(self.widget.viewport().mapToGlobal(pos))
        if chosen == activate_all_action:
            self.set_multiple_system_entries_active_by_keys(
                "Places",
                [entry['key'] for entry in all_entries],
                not all_active,
            )
            return True
        return chosen is not None

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
        self.widget.clear()
        self.build_from_data(self.loaded_data)

    def rename_custom_entry(self, item):
        current_name = (item.text(0) or '').strip() or 'Favorit'

        dialog = QInputDialog(self.widget)
        dialog.setWindowTitle(app_tr('NavigatorManager', 'Favorit umbenennen'))
        dialog.setLabelText(app_tr('NavigatorManager', 'Name:'))
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

        group_name = self._normalize_group_name(parent.data(0, ROLE_GROUP_NAME) or parent.text(0) or '')
        entry_key = item.data(0, ROLE_ENTRY_KEY)
        if not group_name or not entry_key:
            return

        self.set_system_entry_active_by_key(group_name, str(entry_key), bool(active))

    def set_system_entry_active_by_key(self, group_name, entry_key, active):
        group_name = self._normalize_group_name(group_name)
        groups = self.loaded_data.get('groups', []) if isinstance(self.loaded_data, dict) else []
        for group in groups:
            if self._normalize_group_name(group.get('name', '')) != group_name:
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
        group_name = self._normalize_group_name(group_name)
        keys = set(str(key) for key in entry_keys if key)
        if not keys:
            return

        groups = self.loaded_data.get('groups', []) if isinstance(self.loaded_data, dict) else []
        changed = False
        for group in groups:
            if self._normalize_group_name(group.get('name', '')) != group_name:
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
        result = []
        for entry in self.get_all_system_entries(group_name):
            if entry.get('active', True):
                continue
            result.append(
                {
                    'label': entry.get('label', ''),
                    'key': entry.get('key', ''),
                    'icon': entry.get('icon', ''),
                }
            )
        return result

    def get_all_system_entries(self, group_name):
        entries = self._group_entries_with_system_defaults(group_name)
        result = []
        for idx, entry in enumerate(entries):
            if not isinstance(entry, dict):
                continue
            if entry.get('type') == 'separator':
                continue
            source = str(entry.get('source', 'system')).strip()
            if source != 'system':
                continue
            result.append(
                {
                    'label': self._canonical_system_label(entry.get('dynamic', ''), entry.get('label') or ''),
                    'key': self.build_entry_key(entry, idx),
                    'icon': entry.get('icon', ''),
                    'active': bool(entry.get('active', True)),
                }
            )
        return result

    def _group_entries_with_system_defaults(self, group_name):
        group_name = self._normalize_group_name(group_name)
        default_groups = DEFAULT_NAVIGATOR_DATA.get('groups', []) if isinstance(DEFAULT_NAVIGATOR_DATA, dict) else []
        loaded_groups = self.loaded_data.get('groups', []) if isinstance(self.loaded_data, dict) else []

        default_group = next(
            (group for group in default_groups if self._normalize_group_name(group.get('name', '')) == group_name),
            None,
        )
        loaded_group = next(
            (group for group in loaded_groups if self._normalize_group_name(group.get('name', '')) == group_name),
            None,
        )

        default_entries = list(default_group.get('entries', [])) if isinstance(default_group, dict) else []
        loaded_entries = list(loaded_group.get('entries', [])) if isinstance(loaded_group, dict) else []
        if not default_entries and loaded_entries:
            return loaded_entries

        loaded_system_by_key = {}
        loaded_custom_entries = []
        for idx, entry in enumerate(loaded_entries):
            if not isinstance(entry, dict):
                continue
            source = str(entry.get('source', 'system')).strip()
            if source == 'custom':
                loaded_custom_entries.append(copy.deepcopy(entry))
                continue
            key = self.build_entry_key(entry, idx)
            loaded_system_by_key[key] = entry

        merged_entries = []
        for idx, entry in enumerate(default_entries):
            if not isinstance(entry, dict):
                continue
            merged = copy.deepcopy(entry)
            key = self.build_entry_key(entry, idx)
            loaded_entry = loaded_system_by_key.get(key)
            if isinstance(loaded_entry, dict):
                for field in ('active', 'icon', 'label', 'path'):
                    if field in loaded_entry:
                        merged[field] = loaded_entry[field]
            merged_entries.append(merged)

        merged_entries.extend(loaded_custom_entries)
        return merged_entries

    def get_entry_path(self, item: QTreeWidgetItem):
        if item.data(0, ROLE_KIND) != 'entry':
            return None
        path = item.data(0, ROLE_PATH)
        if not path:
            return None
        return path

    def get_entry_location(self, item: QTreeWidgetItem):
        if item is None or item.data(0, ROLE_KIND) != 'entry':
            return None
        path = item.data(0, ROLE_PATH)
        if not path:
            return None
        kind = str(item.data(0, ROLE_LOCATION_KIND) or "local").strip().lower()
        if kind not in {"local", "remote"}:
            kind = "local"
        remote_id = item.data(0, ROLE_REMOTE_ID)
        return PaneLocation(
            kind=kind,
            path=str(path),
            remote_id=str(remote_id) if remote_id else None,
        )

    def refresh(self):
        self.widget.clear()
        self.loaded_data = self.load_data()
        self.build_from_data(self.loaded_data)

    def on_item_collapsed(self, item: QTreeWidgetItem):
        if item.data(0, ROLE_KIND) != 'group':
            return
        if not bool(item.data(0, ROLE_COLLAPSIBLE)):
            item.setExpanded(True)

    def resolve_entry_data(self, entry):
        if str(entry.get("source", "system")).strip() == "remote":
            remote_path = str(entry.get("path") or "/").strip() or "/"
            if not remote_path.startswith("/"):
                remote_path = f"/{remote_path}"
            return {
                "label": entry.get("label", ""),
                "path": remote_path,
                "icon": entry.get("icon", "folder-cloud"),
                "source": "remote",
                "location_kind": "remote",
                "remote_id": str(entry.get("remote_id") or "").strip(),
                "dynamic": "",
            }

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
            # keep raw label empty so build_from_data will use token for translation
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'user-home'
        elif dynamic_token == 'trash':
            dynamic_entry['path'] = os.path.expanduser('~/.local/share/Trash/files')
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'user-trash'
        elif dynamic_token == 'desktop':
            desktop_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DesktopLocation)
            dynamic_entry['path'] = desktop_path or os.path.expanduser('~/Desktop')
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'user-desktop'
        elif dynamic_token == 'documents':
            documents_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
            dynamic_entry['path'] = documents_path or os.path.expanduser('~/Documents')
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'folder-documents'
        elif dynamic_token == 'downloads':
            downloads_path = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
            dynamic_entry['path'] = downloads_path or os.path.expanduser('~/Downloads')
            dynamic_entry['icon'] = dynamic_entry['icon'] or 'folder-download'
        else:
            return entry

        return dynamic_entry

    def _remote_entries(self):
        if self.remote_mount_settings is None:
            return []
        if not hasattr(self.remote_mount_settings, "build_navigator_entries"):
            return []
        try:
            return list(self.remote_mount_settings.build_navigator_entries(self.remote_connection_settings))
        except Exception:
            return []

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
                continue

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
            result = []
            try:
                for child in path_obj.iterdir():
                    try:
                        if child.is_dir():
                            result.append(child)
                    except (OSError, PermissionError):
                        continue
            except (OSError, PermissionError):
                return []
            return result

        def add_path(path):
            expanded_path = os.path.expanduser(path)
            try:
                if not os.path.isdir(expanded_path):
                    return
            except (OSError, PermissionError):
                return
            normalized = os.path.normpath(expanded_path)
            if normalized in seen_paths:
                return
            seen_paths.add(normalized)
            drive_paths.append(normalized)

        add_path('/')

        for base in ['/mnt', '/media']:
            base_path = Path(base)
            try:
                if base_path.is_dir():
                    for entry in sorted(iter_subdirs(base_path)):
                        add_path(str(entry))
            except (OSError, PermissionError):
                continue

        run_media_base = Path('/run/media')
        try:
            if run_media_base.is_dir():
                try:
                    for user_dir in sorted(iter_subdirs(run_media_base)):
                        try:
                            for mount_dir in sorted(iter_subdirs(user_dir)):
                                add_path(str(mount_dir))
                        except (OSError, PermissionError):
                            continue
                except (OSError, PermissionError):
                    pass
        except (OSError, PermissionError):
            pass

        entries = []
        for path in drive_paths:
            label = 'Root' if path == '/' else Path(path).name
            entries.append({
                'label': label,
                'path': path,
                'icon': 'drive-harddisk',
            })

        return entries
