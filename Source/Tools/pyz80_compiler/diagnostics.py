"""Стабильные диагностические сообщения компилятора с координатами исходника."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, order=True)
class SourceSpan:
    """Полуинтервал исходного Python-текста."""

    path: str
    line: int
    column: int
    end_line: int
    end_column: int

    @classmethod
    def from_node(cls, path: Path, node: object) -> "SourceSpan":
        line = int(getattr(node, "lineno", 1))
        column = int(getattr(node, "col_offset", 0))
        end_line = int(getattr(node, "end_lineno", line))
        end_column = int(getattr(node, "end_col_offset", column + 1))
        return cls(
            path=str(path).replace("\\", "/"),
            line=line,
            column=column,
            end_line=end_line,
            end_column=end_column,
        )

    def render(self) -> str:
        return f"{self.path}:{self.line}:{self.column + 1}"


@dataclass(frozen=True)
class Diagnostic:
    """Одно воспроизводимое сообщение без зависимости от абсолютного cwd."""

    code: str
    message: str
    span: SourceSpan | None = None

    def render(self) -> str:
        location = f"{self.span.render()}: " if self.span is not None else ""
        return f"{location}{self.code}: {self.message}"


class CompileError(RuntimeError):
    """Ошибка, после которой выходные файлы не должны изменяться."""

    def __init__(self, diagnostic: Diagnostic):
        super().__init__(diagnostic.render())
        self.diagnostic = diagnostic


def fail(code: str, message: str, span: SourceSpan | None = None) -> "None":
    raise CompileError(Diagnostic(code=code, message=message, span=span))
