"""Domain-level exceptions.

Domain modules raise these instead of ``fastapi.HTTPException`` so they don't
depend on the web framework and can be unit-tested without it. The API layer
registers a single handler (see ``clippyme.api.app``) that maps any
``ClippyMeError`` to an HTTP response using its ``status_code`` / ``detail``.
"""


class ClippyMeError(Exception):
    """Base domain error. Carries an HTTP-ish status code + a user-facing detail."""

    status_code = 500

    def __init__(self, detail: str, status_code: int | None = None):
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(detail)


class ValidationError(ClippyMeError):
    """Bad/insufficient input (maps to 400)."""

    status_code = 400


class NotFoundError(ClippyMeError):
    """A requested resource (clip, job, metadata) doesn't exist (maps to 404)."""

    status_code = 404


class ComposeError(ClippyMeError):
    """A compose/render step failed (maps to 400 by default)."""

    status_code = 400
