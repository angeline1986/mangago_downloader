"""Typed errors emitted by the Lezhin capture core."""


class LezhinError(RuntimeError):
    """Base class for safe, user-facing provider failures."""


class LezhinSessionError(LezhinError):
    """The dedicated, manually authenticated Chrome session is unavailable."""


class LezhinReaderError(LezhinError):
    """The episode reader is inaccessible or its structure is unsupported."""


class LezhinCaptureError(LezhinError):
    """A response could not be safely associated with an indexed cut."""


class LezhinIncompleteError(LezhinError):
    """The persisted set does not contain every valid expected cut."""
