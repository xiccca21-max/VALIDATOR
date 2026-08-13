"""Safe adversarial training arena for the PDF validator."""

from .adapter import PdfCheckResult, StructuralCheckResult, Verdict

__all__ = ["PdfCheckResult", "StructuralCheckResult", "Verdict"]
