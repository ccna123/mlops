"""Shared FastAPI dependencies.

`require_auth` does nothing today. Section 3.2 of the design doc says auth
is not needed while this runs locally for one person, but that it becomes
mandatory before anything is exposed. Declaring the dependency now means
that change touches ONE function instead of eleven routes, with no chance
of missing one.
"""

from __future__ import annotations


def require_auth() -> None:
    """Authorises the caller.

    Args:
        None.

    Returns:
        Nothing. Today every caller is allowed: the stack runs on localhost
        for a single user. When an API key is added, this is the only place
        that changes.

    Example:
        # Every route declares it, so none of them has to be edited later:
        @router.get("/models", dependencies=[Depends(require_auth)])
        def list_models():
            ...
    """
    return None
