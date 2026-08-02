"""csvpeek: a fast, zero-dependency CSV profiler for the terminal."""

from .core import ColumnProfile, Profile, profile_rows, profile_file

__version__ = "0.2.0"
__all__ = ["ColumnProfile", "Profile", "profile_rows", "profile_file", "__version__"]
