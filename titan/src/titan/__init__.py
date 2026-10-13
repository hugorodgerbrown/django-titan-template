"""titan: provision and launch a Titan app on Render, shared-db and Resend."""

__version__ = "2.1.0"


class TitanError(Exception):
    """A step failed; the message says what to do about it."""
