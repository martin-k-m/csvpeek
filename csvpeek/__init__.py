"""csvpeek: a fast, zero-dependency CSV profiler for the terminal."""

from .core import (
    DEFAULT_ENCODING,
    SCHEMA_VERSION,
    ColumnProfile,
    Histogram,
    Profile,
    ProfileError,
    profile_file,
    profile_rows,
)

__version__ = "1.2.0"
__all__ = [
    "DEFAULT_ENCODING",
    "SCHEMA_VERSION",
    "ColumnProfile",
    "Histogram",
    "Profile",
    "ProfileError",
    "__version__",
    "profile_file",
    "profile_rows",
]
