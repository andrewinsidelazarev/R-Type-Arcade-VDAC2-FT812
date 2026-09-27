"""Ошибка трансляции с местом в исходнике."""
from __future__ import annotations


class TranslationError(Exception):
    """Конструкция вне поддержанного подмножества или противоречие типов."""

    def __init__(self, message: str, node: object | None = None,
                 filename: str | None = None) -> None:
        line = getattr(node, 'lineno', None)
        short = (filename or '?').replace('\\', '/').rsplit('/', 1)[-1]
        where = f'{short}:{line}' if line is not None else (short if filename else '')
        super().__init__(f'{where}: {message}' if where else message)
        self.node = node
        self.filename = filename
