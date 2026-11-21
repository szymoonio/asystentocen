"""Błędy stron modułu B jako strony HTML (main.py jest zamrożony, więc bez exception_handler)."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Callable

from fastapi import Request

from app.templating import render


class PageError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


_TITLES = {403: "Brak dostępu", 404: "Nie znaleziono", 409: "Konflikt wersji"}


def _error_page(request: Request, err: PageError):
    response = render(
        request, "assistant/blad.html", title=_TITLES.get(err.status, "Błąd"), message=err.message
    )
    response.status_code = err.status
    return response


def html_errors(fn: Callable) -> Callable:
    """Zamienia `PageError` na stronę błędu. Endpoint musi mieć parametr `request`."""

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except PageError as err:
                return _error_page(kwargs["request"], err)

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except PageError as err:
            return _error_page(kwargs["request"], err)

    return wrapper
