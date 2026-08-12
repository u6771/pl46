from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from skeletonfont.errors import ProjectDataError
from skeletonfont.glyph_source_io import load_glyph_source
from skeletonfont.model import GlyphSource

from .identity import GlyphIdentityMap


IDENTITY_MAP_PATH = Path(__file__).with_name("glyph_identity_map.json")


@dataclass(frozen=True, slots=True)
class GlyphFileEntry:
    path: Path
    source: GlyphSource | None
    error: str | None

    @property
    def display_name(self) -> str:
        return self.path.stem if self.source is None else self.source.name


@dataclass(frozen=True, slots=True)
class GlyphFileMove:
    source: Path
    destination: Path


class SourceWorkspace:
    def __init__(self, project_directory: Path) -> None:
        self.project_directory = project_directory.resolve()
        self.source_root = self.project_directory / "glyph_sources"
        if not self.source_root.is_dir():
            raise ProjectDataError(
                f"Glyph source directory does not exist: {self.source_root}"
            )
        self.identity_map = GlyphIdentityMap.load(IDENTITY_MAP_PATH)
        self._entry_cache: dict[
            Path, tuple[tuple[int, int], GlyphFileEntry]
        ] = {}

    def source_directories(self) -> tuple[Path, ...]:
        return (self.source_root,) + tuple(
            sorted(
                (path for path in self.source_root.rglob("*") if path.is_dir()),
                key=lambda path: tuple(
                    part.casefold()
                    for part in path.relative_to(self.source_root).parts
                ),
            )
        )

    def validate_source_directory(self, path: Path) -> Path:
        resolved = path.resolve()
        try:
            resolved.relative_to(self.source_root.resolve())
        except ValueError as error:
            raise ProjectDataError(
                f"Source directory is outside glyph_sources: {resolved}"
            ) from error
        if not resolved.is_dir():
            raise ProjectDataError(f"Source directory does not exist: {resolved}")
        return resolved

    def glyphs_in(self, source_directory: Path) -> tuple[GlyphFileEntry, ...]:
        directory = self.validate_source_directory(source_directory)
        entries = [self._load_glyph_entry(path) for path in directory.glob("*.json")]
        entries.sort(key=self._glyph_sort_key)
        return tuple(entries)

    def all_glyphs(self) -> tuple[GlyphFileEntry, ...]:
        entries = [
            self._load_glyph_entry(path)
            for path in self.source_root.rglob("*.json")
        ]
        entries.sort(
            key=lambda entry: (
                tuple(
                    part.casefold()
                    for part in entry.path.parent.relative_to(
                        self.source_root
                    ).parts
                ),
                self._glyph_sort_key(entry),
            )
        )
        return tuple(entries)

    def move_glyphs(
        self,
        paths: tuple[Path, ...],
        target_directory: Path,
    ) -> tuple[GlyphFileMove, ...]:
        moves = self.plan_glyph_moves(paths, target_directory)
        self.execute_glyph_moves(moves)
        return moves

    def plan_glyph_moves(
        self,
        paths: tuple[Path, ...],
        target_directory: Path,
    ) -> tuple[GlyphFileMove, ...]:
        target = self.validate_source_directory(target_directory)
        root = self.source_root.resolve()
        moves: list[GlyphFileMove] = []
        destinations: dict[Path, Path] = {}
        conflicts: list[str] = []

        for path in paths:
            source = path.resolve()
            try:
                source.relative_to(root)
            except ValueError:
                conflicts.append(f"outside glyph_sources: {source}")
                continue
            if not source.is_file() or source.suffix.casefold() != ".json":
                conflicts.append(f"not a glyph source file: {source}")
                continue
            destination = target / source.name
            if source.parent == target:
                continue
            previous_source = destinations.get(destination)
            if previous_source is not None:
                conflicts.append(
                    f"{previous_source} and {source} both become {destination}"
                )
                continue
            destinations[destination] = source
            if destination.exists():
                conflicts.append(f"already exists: {destination}")
                continue
            moves.append(GlyphFileMove(source, destination))

        if conflicts:
            details = "\n".join(f"- {item}" for item in conflicts)
            raise ProjectDataError(f"Cannot move glyph sources:\n{details}")

        return tuple(moves)

    def execute_glyph_moves(self, moves: tuple[GlyphFileMove, ...]) -> None:
        completed: list[GlyphFileMove] = []
        try:
            for move in moves:
                if move.destination.exists():
                    raise FileExistsError(
                        f"destination appeared after validation: "
                        f"{move.destination}"
                    )
                move.source.rename(move.destination)
                completed.append(move)
        except OSError as error:
            rollback_errors: list[str] = []
            for move in reversed(completed):
                try:
                    move.destination.rename(move.source)
                except OSError as rollback_error:
                    rollback_errors.append(
                        f"{move.destination} -> {move.source}: {rollback_error}"
                    )
            suffix = (
                "\nRollback also failed:\n"
                + "\n".join(f"- {item}" for item in rollback_errors)
                if rollback_errors
                else ""
            )
            raise ProjectDataError(
                f"Cannot move {move.source} to {move.destination}: {error}{suffix}"
            ) from error
        for move in moves:
            self._entry_cache.pop(move.source.resolve(), None)
            self._entry_cache.pop(move.destination.resolve(), None)

    def _load_glyph_entry(self, path: Path) -> GlyphFileEntry:
        # source_root is resolved at construction, so rglob/glob already yields
        # absolute paths. Avoid Path.resolve() here: it is surprisingly costly
        # when the browser checks a few thousand cached entries.
        resolved = path if path.is_absolute() else path.resolve()
        try:
            stat = resolved.stat()
        except OSError as error:
            return GlyphFileEntry(resolved, None, str(error))
        signature = (stat.st_mtime_ns, stat.st_size)
        cached = self._entry_cache.get(resolved)
        if cached is not None and cached[0] == signature:
            return cached[1]
        try:
            source = load_glyph_source(resolved)
            self.identity_map.validate_source(source, resolved)
        except (OSError, ValueError) as error:
            entry = GlyphFileEntry(resolved, None, str(error))
        else:
            entry = GlyphFileEntry(resolved, source, None)
        self._entry_cache[resolved] = (signature, entry)
        return entry

    @staticmethod
    def _glyph_sort_key(entry: GlyphFileEntry) -> tuple[int, int, str, str]:
        if entry.source is None:
            return 2, 0, entry.path.stem.casefold(), entry.path.name.casefold()
        if entry.source.codepoint is None:
            return 1, 0, entry.source.name.casefold(), entry.path.name.casefold()
        return 0, entry.source.codepoint, "", entry.path.name.casefold()
