"""csvpeek: a fast, zero-dependency CSV profiler for the terminal."""

from .core import (
    SCHEMA_VERSION,
    ColumnProfile,
    Histogram,
    Profile,
    ProfileError,
    profile_rows,
    profile_file,
)

__version__ = "1.1.0"
__all__ = [
    "SCHEMA_VERSION",
    "ColumnProfile",
    "Histogram",
    "Profile",
    "ProfileError",
    "profile_rows",
    "profile_file",
    "__version__",
]
