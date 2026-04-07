from __future__ import annotations

from pathlib import Path


class LinkService:
    def create_links(self, source_paths, target_directory: str) -> list[str]:
        created: list[str] = []
        target_dir = Path(target_directory)
        if not target_dir.exists():
            return created

        for source in source_paths:
            source_path = Path(source)
            if not source_path.exists():
                continue

            target_path = target_dir / source_path.name
            if target_path.exists():
                continue

            try:
                target_path.symlink_to(source_path)
                created.append(str(target_path))
            except (FileExistsError, FileNotFoundError, OSError, ValueError):
                continue

        return created
