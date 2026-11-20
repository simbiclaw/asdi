"""Shared ASDI runtime errors."""


class RuntimeErrorStateError(RuntimeError):
    """The launcher cannot safely perform the requested state transition."""
