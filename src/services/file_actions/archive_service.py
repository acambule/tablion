from __future__ import annotations

from pathlib import Path

from localization import app_tr


class ArchiveService:
    def selected_archive_path(self, paths: list[str], *, file_operations) -> str | None:
        if len(paths) != 1:
            return None
        archive_path = str(Path(paths[0]))
        path_obj = Path(archive_path)
        if not path_obj.exists() or path_obj.is_dir():
            return None
        if not file_operations.is_supported_archive(path_obj):
            return None
        return archive_path

    def archive_creation_sources(self, paths: list[str]) -> list[str]:
        if len(paths) < 2:
            return []
        return [str(Path(path)) for path in paths if Path(path).exists()]

    def default_archive_target_path(self, sources: list[str], suffix: str) -> str:
        source_paths = [Path(source) for source in sources]
        parent_counts: dict[Path, int] = {}
        for source_path in source_paths:
            parent_counts[source_path.parent] = parent_counts.get(source_path.parent, 0) + 1

        target_parent = max(parent_counts, key=parent_counts.get) if parent_counts else Path.home()
        if len(source_paths) == 2:
            stem = f"{source_paths[0].stem}-{source_paths[1].stem}"
        else:
            stem = app_tr("PaneController", "Archiv")
        return str(target_parent / f"{stem}{suffix}")

    def archive_suffix_for_filter(self, selected_filter: str, available_filters: list[tuple[str, str]]) -> str:
        for filter_label, suffix in available_filters:
            if selected_filter == filter_label:
                return suffix
        return ".zip"

    def build_archive_path(self, selected_path: str, suffix: str) -> Path:
        archive_path = Path(selected_path)
        if not archive_path.name.lower().endswith(suffix):
            archive_path = archive_path.with_name(f"{archive_path.name}{suffix}")
        return archive_path

    def extract_archive(self, archive_path: str, destination: str, *, file_operations):
        archive_obj = Path(archive_path)
        return file_operations.extract_archive(archive_obj, destination)

    def create_archive(self, source_paths: list[str], archive_path: Path, *, file_operations):
        return file_operations.create_archive(source_paths, archive_path, overwrite=False)
