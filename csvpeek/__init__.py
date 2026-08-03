"""csvpeek: a fast, zero-dependency CSV profiler for the terminal."""

from .core import (
    SCHEMA_VERSION,
    ColumnProfile,
    Profile,
    ProfileError,
    profile_rows,
    profile_file,
)

__version__ = "0.2.0"
__all__ = [
    "SCHEMA_VERSION",
    "ColumnProfile",
    "Profile",
    "ProfileError",
    "profile_rows",
    "profile_file",
    "__version__",
]
