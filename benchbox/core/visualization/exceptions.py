from __future__ import annotations


class VisualizationError(Exception):
    pass


class VisualizationDependencyError(VisualizationError):
    def __init__(self, package: str, advice: str | None = None):
        message = f"Visualization dependency '{package}' is not installed."
        if advice:
            message = f"{message} {advice}"
        super().__init__(message)
        self.package = package
        self.advice = advice
