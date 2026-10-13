"""Stable command-line entry for preview, benchmark and Discord modes."""
from .runtime.execution import cancellable_main, main, run

__all__ = ["cancellable_main", "main", "run"]

if __name__ == "__main__":
    raise SystemExit(main())
