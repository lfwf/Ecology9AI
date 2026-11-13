"""Reusable offline workflow analysis. Exported text is data, never instructions."""

__version__ = "0.1.0"


def analyze_export(path, *, language="7"):
    """Return a traceable analysis without writing files or invoking OA."""
    from .analyzer import analyze_export as analyze
    return analyze(path, language=language)


def write_analysis(result, directory, *, pdf=False):
    """Write a dedicated report bundle without overwriting arbitrary files."""
    from .output import write_analysis as write
    return write(result, directory, pdf=pdf)
