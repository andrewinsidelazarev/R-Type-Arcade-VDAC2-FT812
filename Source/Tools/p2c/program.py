"""Исходная программа: модули пакета, классы, иерархия, методы и dataclass-поля."""
from __future__ import annotations

import ast
import copy
import dataclasses
import importlib
import inspect
from dataclasses import dataclass, field
from pathlib import Path

from .errors import TranslationError


@dataclass
class ClassInfo:
    name: str
    module: str
    filename: str
    node: ast.ClassDef
    python: type
    bases: list[str] = field(default_factory=list)          # классы пакета
    list_base: ast.expr | None = None                        # class X(list[T])
    methods: dict[str, ast.FunctionDef] = field(default_factory=dict)
    annotations: dict[str, ast.expr] = field(default_factory=dict)
    children: list[str] = field(default_factory=list)
    is_dataclass: bool = False
    frozen: bool = False
    synthesized: dict[str, ast.FunctionDef] = field(default_factory=dict)

    def method_kind(self, name: str) -> str:
        node = self.methods.get(name) or self.synthesized.get(name)
        decorators = [ast.unparse(item) for item in node.decorator_list]
        if decorators == ['property']:
            return 'property'
        if decorators == ['staticmethod']:
            return 'staticmethod'
        if decorators == ['classmethod']:
            return 'classmethod'
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
    imports: dict[str, tuple[str, str]] = field(default_factory=dict)  # имя -> (модуль, объект)


class Program:
    """Индекс исходников пакета; объекты берутся из уже импортированных модулей."""

    def __init__(self, package: str, module_names: list[str], extra_modules: tuple[str, ...] = ()) -> None:
        self.package = package
        self.modules: dict[str, ModuleInfo] = {}
        self.classes: dict[str, ClassInfo] = {}
        for short in module_names:
            self._load_module(f'{package}.{short}')
        # Модули вне пакета (кадр программы в инструментах) импортируют пакет абсолютно.
        for name in extra_modules:
            self._load_module(name)
        for info in self.classes.values():
            for base in info.bases:
                self.classes[base].children.append(info.name)
        for info in self.classes.values():
            if info.is_dataclass:
                self._synthesize_init(info)

    # --- загрузка -----------------------------------------------------------

    def _load_module(self, name: str) -> None:
        python = importlib.import_module(name)
        filename = Path(inspect.getfile(python))
        tree = ast.parse(filename.read_text(encoding='utf-8'), str(filename))
        module = ModuleInfo(name, str(filename), tree, python)
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                self._load_class(module, node)
            elif isinstance(node, ast.FunctionDef):
                module.functions[node.name] = FunctionInfo(node.name, name, str(filename), node)
            elif isinstance(node, ast.ImportFrom) and node.level == 1:
                for alias in node.names:
                    module.imports[alias.asname or alias.name] = (
                        f'{self.package}.{node.module}', alias.name)
            elif (isinstance(node, ast.ImportFrom) and node.level == 0 and node.module
                  and node.module.startswith(self.package + '.')):
                for alias in node.names:
                    module.imports[alias.asname or alias.name] = (node.module, alias.name)
        self.modules[name] = module

    def _load_class(self, module: ModuleInfo, node: ast.ClassDef) -> None:
        python = getattr(module.python, node.name)
        info = ClassInfo(node.name, module.name, module.filename, node, python)
        for base in node.bases:
            text = ast.unparse(base)
            if isinstance(base, ast.Subscript) and ast.unparse(base.value) == 'list':
                info.list_base = base.slice
            elif isinstance(base, ast.Name):
                info.bases.append(base.id)
            else:
                raise TranslationError(f'база класса {text} не поддержана', node, module.filename)
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                info.methods[item.name] = item
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                info.annotations[item.target.id] = item.annotation
        for method in info.methods.values():
            for part in ast.walk(method):
                if (isinstance(part, ast.AnnAssign) and isinstance(part.target, ast.Attribute) and
                        isinstance(part.target.value, ast.Name) and part.target.value.id == 'self'):
                    info.annotations.setdefault(part.target.attr, part.annotation)
        info.is_dataclass = dataclasses.is_dataclass(python) and '__dataclass_fields__' in python.__dict__
        if info.is_dataclass:
            info.frozen = python.__dataclass_params__.frozen
        elif dataclasses.is_dataclass(python):
            # Наследник dataclass без собственного декоратора: неизменяемость базы.
            info.frozen = python.__dataclass_params__.frozen
        if node.name in self.classes:
            raise TranslationError(f'класс {node.name} объявлен в двух модулях')
        module.classes[node.name] = info
        self.classes[node.name] = info

    def _synthesize_init(self, info: ClassInfo) -> None:
        """AST `__init__`, созданного dataclass, если класс не задал свой."""
        if '__init__' in info.methods:
            return
        python = info.python
        arguments = []
        defaults = []
        body: list[ast.stmt] = []
        line = info.node.lineno
        for item in dataclasses.fields(python):
            if not item.init:
                raise TranslationError(f'{info.name}.{item.name}: поле init=False не поддержано',
                                       info.node, info.filename)
            annotation = ast.parse(item.type, mode='eval').body if isinstance(item.type, str) else None
            if annotation is None:
                raise TranslationError(f'{info.name}.{item.name}: аннотация не строка', info.node, info.filename)
            arguments.append(ast.arg(arg=item.name, annotation=annotation))
            if item.default is not dataclasses.MISSING:
                defaults.append(self._default_node(item.default, info))
            elif item.default_factory is not dataclasses.MISSING:
                factory = item.default_factory
                if factory not in (list, dict, set):
                    raise TranslationError(f'{info.name}.{item.name}: default_factory {factory} не поддержан',
                                           info.node, info.filename)
                defaults.append(ast.Call(func=ast.Name(id=factory.__name__, ctx=ast.Load()),
                                         args=[], keywords=[]))
            elif defaults:
                raise TranslationError(f'{info.name}: поле без умолчания после поля с умолчанием',
                                       info.node, info.filename)
            target = ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()), attr=item.name, ctx=ast.Store())
            body.append(ast.Assign(targets=[target], value=ast.Name(id=item.name, ctx=ast.Load())))
        post = self.find_method(info.name, '__post_init__')
        if post is not None:
            call = ast.Call(func=ast.Attribute(value=ast.Name(id='self', ctx=ast.Load()),
                                               attr='__post_init__', ctx=ast.Load()),
                            args=[], keywords=[])
            body.append(ast.Expr(value=call))
        if not body:
            body.append(ast.Pass())
        function = ast.FunctionDef(
            name='__init__',
            args=ast.arguments(posonlyargs=[], args=[ast.arg(arg='self')] + arguments, vararg=None,
                               kwonlyargs=[], kw_defaults=[], kwarg=None, defaults=defaults),
            body=body, decorator_list=[], returns=ast.Constant(value=None), type_params=[])
        for part in ast.walk(function):
            if hasattr(part, 'lineno') or isinstance(part, (ast.expr, ast.stmt, ast.arg)):
                part.lineno = line
                part.col_offset = 0
                part.end_lineno = line
                part.end_col_offset = 0
        info.synthesized['__init__'] = function

    @staticmethod
    def _default_node(value: object, info: ClassInfo) -> ast.expr:
        if value is None or isinstance(value, (bool, int, str)):
            return ast.Constant(value=value)
        if isinstance(value, tuple) and all(isinstance(item, (bool, int, str)) or item is None
                                            for item in value):
            return ast.Tuple(elts=[ast.Constant(value=item) for item in value], ctx=ast.Load())
        raise TranslationError(f'{info.name}: умолчание {value!r:.40} не поддержано', info.node, info.filename)

    # --- иерархия -------------------------------------------------------------

    def class_of(self, value: object) -> ClassInfo | None:
        python_type = type(value)
        info = self.classes.get(python_type.__name__)
        if info is not None and info.python is python_type:
            return info
        return None

    def root(self, name: str) -> str:
        info = self.classes[name]
        while info.bases:
            if len(info.bases) != 1:
                raise TranslationError(f'множественное наследование {info.name} не поддержано',
                                       info.node, info.filename)
            info = self.classes[info.bases[0]]
        return info.name

    def ancestors(self, name: str) -> list[str]:
        """Класс и его базы пакета снизу вверх."""
        result = [name]
        info = self.classes[name]
        while info.bases:
            info = self.classes[info.bases[0]]
            result.append(info.name)
        return result

    def is_subclass(self, name: str, base: str) -> bool:
        return base in self.ancestors(name)

    def lca(self, left: str, right: str) -> str | None:
        right_chain = set(self.ancestors(right))
        for name in self.ancestors(left):
            if name in right_chain:
                return name
        return None

    def descendants(self, name: str) -> list[str]:
        """Класс и все его подклассы в прямом порядке обхода."""
        result = []
        stack = [name]
        while stack:
            current = stack.pop()
            result.append(current)
            stack.extend(reversed(self.classes[current].children))
        return result

    def find_method(self, class_name: str, method: str) -> tuple[ClassInfo, ast.FunctionDef] | None:
        """Метод по MRO CPython: явный метод или созданный dataclass `__init__`."""
        info = self.classes[class_name]
        for base in info.python.__mro__:
            candidate = self.classes.get(base.__name__)
            if candidate is None or candidate.python is not base:
                if base is list and method in list.__dict__:
                    return None
                continue
            if method in candidate.methods:
                return candidate, candidate.methods[method]
            if method in candidate.synthesized:
                return candidate, candidate.synthesized[method]
        return None

    def class_attribute(self, class_name: str, name: str) -> tuple[bool, object]:
        """Атрибут класса (не метод, не поле экземпляра) по MRO."""
        info = self.classes[class_name]
        for base in info.python.__mro__:
            if name in base.__dict__:
                value = base.__dict__[name]
                if inspect.isfunction(value) or isinstance(value, (property, staticmethod, classmethod)):
                    return False, None
                return True, value
        return False, None

    def list_base_of(self, class_name: str) -> ast.expr | None:
        for name in self.ancestors(class_name):
            if self.classes[name].list_base is not None:
                return self.classes[name].list_base
        return None
