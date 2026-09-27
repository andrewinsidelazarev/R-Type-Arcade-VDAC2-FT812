"""Исходная программа: модули пакета, их AST, классы, функции и константы."""
from __future__ import annotations

import ast
import importlib
import inspect
from dataclasses import dataclass, field
from pathlib import Path

from .ctypes_model import TranslationError


@dataclass
class ClassInfo:
    name: str
    module: str
    filename: str
    node: ast.ClassDef
    python: type
    methods: dict[str, ast.FunctionDef] = field(default_factory=dict)
    # Аннотации полей: класс-уровень (dataclass) и `self.x: T = ...` в методах.
    annotations: dict[str, ast.expr] = field(default_factory=dict)

    def method_kind(self, name: str) -> str:
        node = self.methods[name]
        decorators = [ast.unparse(item) for item in node.decorator_list]
        if decorators == ['property']:
            return 'property'
        if decorators == ['staticmethod']:
            return 'staticmethod'
        if decorators:
            raise TranslationError(f'декоратор {decorators} не поддержан', node, self.filename)
        return 'method'


@dataclass
class FunctionInfo:
    name: str
    module: str
    filename: str
    node: ast.FunctionDef


@dataclass
class ModuleInfo:
    name: str
    filename: str
    tree: ast.Module
    python: object
    classes: dict[str, ClassInfo] = field(default_factory=dict)
    functions: dict[str, FunctionInfo] = field(default_factory=dict)


class Program:
    """Индекс исходников пакета; объекты берутся из уже импортированных модулей."""

    def __init__(self, package: str, module_names: list[str]) -> None:
        self.package = package
        self.modules: dict[str, ModuleInfo] = {}
        self.classes: dict[str, ClassInfo] = {}
        for short in module_names:
            name = f'{package}.{short}'
            python = importlib.import_module(name)
            filename = Path(inspect.getfile(python))
            tree = ast.parse(filename.read_text(encoding='utf-8'), str(filename))
            info = ModuleInfo(name, str(filename), tree, python)
            for node in tree.body:
                if isinstance(node, ast.ClassDef):
                    cls = ClassInfo(node.name, name, str(filename), node, getattr(python, node.name))
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            cls.methods[item.name] = item
                        elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                            cls.annotations[item.target.id] = item.annotation
                    for method in cls.methods.values():
                        for part in ast.walk(method):
                            if (isinstance(part, ast.AnnAssign) and
                                    isinstance(part.target, ast.Attribute) and
                                    isinstance(part.target.value, ast.Name) and
                                    part.target.value.id == 'self'):
                                cls.annotations.setdefault(part.target.attr, part.annotation)
                    info.classes[node.name] = cls
                    if node.name in self.classes:
                        raise TranslationError(f'класс {node.name} объявлен в двух модулях')
                    self.classes[node.name] = cls
                elif isinstance(node, ast.FunctionDef):
                    info.functions[node.name] = FunctionInfo(node.name, name, str(filename), node)
            self.modules[name] = info

    def class_of(self, value: object) -> ClassInfo | None:
        """Описание класса пакета для объекта или None для чужих типов."""
        python_type = type(value)
        info = self.classes.get(python_type.__name__)
        if info is not None and info.python is python_type:
            return info
        return None

    def find_method(self, class_name: str, method: str) -> tuple[ClassInfo, ast.FunctionDef] | None:
        """Метод с учётом одиночного наследования внутри пакета (MRO CPython)."""
        info = self.classes[class_name]
        for base in info.python.__mro__:
            candidate = self.classes.get(base.__name__)
            if candidate is not None and candidate.python is base and method in candidate.methods:
                return candidate, candidate.methods[method]
        return None
