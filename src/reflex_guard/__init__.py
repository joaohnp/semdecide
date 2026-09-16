"""SemDecide: typed semantic decisions for Unix, CI, and guarded actions."""

from .policy import Decision, decide

__all__ = ["Decision", "decide"]
__version__ = "0.2.0"
