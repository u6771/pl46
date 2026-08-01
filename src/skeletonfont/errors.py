from __future__ import annotations


class ProjectDataError(ValueError):
    """Raised when project input cannot be normalized safely."""


class AssemblyError(ProjectDataError):
    """Raised when individually valid inputs cannot form one glyph set."""


class PlanError(ProjectDataError):
    """Raised when an assembled font cannot be resolved into build values."""


class RenderError(ProjectDataError):
    """Raised when a resolved plan cannot be rendered into outlines."""


class CompileError(ProjectDataError):
    """Raised when an in-memory UFO cannot be compiled or saved."""


class BuildError(ProjectDataError):
    """Raised when the complete build pipeline cannot run safely."""
