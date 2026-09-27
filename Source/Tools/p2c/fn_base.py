"""База транслятора функции: значения, имена, целые, преобразования представлений."""
from __future__ import annotations

import ast
import builtins
import re
from dataclasses import dataclass

from .compiler import INT_EMPTY, Capture, Compiler, Plan, describe, int_empty
from .errors import TranslationError
from .intervals import BOOL_RANGE, INT32_MAX, INT32_MIN, TOP, Interval, refine_compare, NEGATED, SWAPPED
from .ptypes import (
    BOOL, BOTTOM, I16, I32, IMAGE, INT_TOP, NONE, STR, U16, U8, VOID, ArrayT, BoolT, BottomT,
    BytesT, CInt, DequeT, DictT, FnT, FontT, ImageT, IntT, ListT, NoneT, ObjT, OptT, SetT, StrT,
    T, TargetT, TupleT, ValT, VoidT, ExtT, cint_for, contains_bottom, is_int_like, is_pointer,
)

C_KEYWORDS = frozenset('''auto break case char const continue default do double else enum
extern float for goto if inline int long register restrict return short signed sizeof static
struct switch typedef union unsigned void volatile while _Bool _Complex _Imaginary
asm at banked bit code critical data far idata interrupt near naked nonbanked pdata reentrant
sbit sfr sfr16 sfr32 shadowregs smallc using wparam xdata z88dk_fastcall z88dk_callee'''.split())
COMPARE_SYMBOLS = {'Eq': '==', 'NotEq': '!=', 'Lt': '<', 'LtE': '<=', 'Gt': '>', 'GtE': '>='}
I16_RANGE = Interval(-32768, 32767)
U16_RANGE = Interval(0, 65535)
BITS16_RANGE = Interval(-32768, 65535)


class NoConst:
    def __repr__(self) -> str:
        return 'NO_CONST'


NO_CONST = NoConst()


@dataclass
class Value:
    t: T
    code: str = ''
    cwidth: CInt | None = None       # C-тип целого выражения code
    path: str | None = None          # текст lvalue Python (для сужения и уточнений)
    const: object = NO_CONST         # известное значение на этапе трансляции
    meta: tuple | None = None        # ссылка на класс, функцию, модуль, встроенную функцию
    cell: tuple | None = None        # ячейка происхождения: ('local', key) / ('param', name) / ('field', cls, attr)
    display: object = None           # узел дисплея/включения, создавшего контейнер


def cname(name: str) -> str:
    return f'p2c_kw_{name}' if name in C_KEYWORDS else name


class Unknown(Exception):
    """Форма операнда ещё не выведена: проход анализа пропускает выражение."""


class EmitterBase:
    def __init__(self, compiler: Compiler, plan: Plan, emit: bool, crepr) -> None:
        self.c = compiler
        self.p = compiler.program
        self.plan = plan
        self.emit = emit
        self.r = crepr
        self.lines: list[str] = []
        self.indent = 1
        self.temp_counter = 0
        self.module_info = self.p.modules[plan.module]
        self.module = self.module_info.python
        self.param_names = {param.name for param in plan.params}
        self.capture_names = {capture.name for capture in plan.captures}
        self.assigned = self._assigned_names(plan.node)
        # Области видимости включений: имя Python -> ключ локальной переменной.
        self.scopes: list[dict[str, str]] = []
        self.scope_counter = 0
        self.refinements: list[dict[str, Interval]] = [{}]
        self.finally_stack: list[list[ast.stmt]] = []
        self.loop_finally: list[int] = []
        # Пути выражений (имена и цепочки атрибутов), доказанно не None в текущей ветви.
        self.present: set[str] = set()

    # --- утилиты -------------------------------------------------------------

    @property
    def strict(self) -> bool:
        return self.emit or self.c.pessimistic

    def error(self, message: str, node: ast.AST | None) -> TranslationError:
        return TranslationError(f'{self.plan.owner + "." if self.plan.owner else ""}{self.plan.name}: {message}',
                                node, self.plan.filename)

    def unknown(self, node: ast.AST | None = None, what: str = '') -> Unknown | TranslationError:
        if self.emit:
            return self.error(f'форма значения не выведена{": " + what if what else ""}', node)
        return Unknown()

    def line(self, text: str) -> None:
        if self.emit:
            self.lines.append('    ' * self.indent + text)

    def temp(self, value_type: T, prefix: str = 't') -> str:
        self.temp_counter += 1
        name = f'p2c_{prefix}{self.temp_counter}'
        if self.emit:
            if isinstance(value_type, CInt):
                value_type = ('cint', value_type)
            elif isinstance(value_type, BoolT):
                value_type = ('cint', U8)
            self.plan.temps[name] = value_type
        return name

    def struct_argument(self, code: str, target: T) -> str:
        """Аргумент-структура из выражения переносится во временную: SDCC 4.6 (Z80) теряет
        адрес структуры, помещаемой в стек прямо из поля по указателю."""
        if not self.emit or re.fullmatch(r'[A-Za-z_]\w*', code):
            return code
        ctype = self.ctype(target)
        if not (ctype.startswith(('P2cT', 'P2cN', 'P2cV_')) or ctype in ('P2cRect', 'P2cFn')):
            return code
        name = self.temp(target)
        self.line(f'{name} = {code};')
        return name

    def mark(self) -> int:
        return len(self.lines)

    @staticmethod
    def _assigned_names(node: ast.AST) -> set[str]:
        """Локальные имена функции без вложенных функций, лямбд и включений."""
        names: set[str] = set()
        body = node.body if isinstance(node, (ast.FunctionDef, ast.Lambda)) else []
        if isinstance(node, ast.Lambda):
            return names
        stack = list(body)
        while stack:
            item = stack.pop()
            if isinstance(item, (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
                continue
            if isinstance(item, ast.FunctionDef):
                names.add(item.name)
                continue
            if isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del)):
                names.add(item.id)
            if isinstance(item, ast.ExceptHandler) and item.name:
                names.add(item.name)
            stack.extend(ast.iter_child_nodes(item))
        return names

    # --- целые ------------------------------------------------------------------

    def interval_of(self, value: Value) -> Interval | None:
        t = value.t
        if isinstance(t, BoolT):
            return BOOL_RANGE
        if isinstance(t, IntT):
            if int_empty(t):
                return TOP if self.strict else None
            return t.interval
        return None

    def int_value(self, value: Value, node: ast.AST) -> Value:
        """Целое значение (Optional раскрывается: None на этом месте — ошибка CPython)."""
        if isinstance(value.t, OptT) and is_int_like(value.t.inner):
            inner = value.t.inner
            code = f'P2C_UNWRAP({value.code})'
            return Value(inner, code, self.r.cint(inner) if self.emit else None, value.path)
        if self.incomplete(value.t):
            raise self.unknown(node)
        if isinstance(value.t, IntT):
            if int_empty(value.t) and self.strict:
                value = Value(INT_TOP, value.code, value.cwidth or I32, value.path, value.const, value.meta)
            elif int_empty(value.t):
                raise self.unknown(node)
            return value
        if isinstance(value.t, BoolT):
            return value
        raise self.error(f'ожидалось целое, есть {describe(value.t)}', node)

    def width(self, value: Value) -> CInt:
        if value.cwidth is not None:
            return value.cwidth
        if isinstance(value.t, BoolT):
            return U8
        if isinstance(value.t, IntT):
            return self.r.cint(value.t)
        return I32

    def cast(self, value: Value, target: CInt, node: ast.AST) -> str:
        """Код значения в C-типе target; сужение только при доказанном интервале."""
        value = self.int_value(value, node)
        width = self.width(value)
        if width == target:
            return value.code
        interval = self.interval_of(value) or width.interval()
        if interval.within(target.minimum, target.maximum) or target.bits == 32 or not self.emit:
            return f'(({target.c()}){value.code})'
        raise self.error(f'значение {interval.lo}…{interval.hi} не помещается в {target.c()}', node)

    def store_int(self, target: CInt, value: Value, node: ast.AST) -> str:
        """Запись целого в ячейку C-типа target (проверка на ПК в проверочной сборке)."""
        value = self.int_value(value, node)
        width = self.width(value)
        if width == target:
            return value.code
        interval = self.interval_of(value) or width.interval()
        if self.emit and not interval.within(target.minimum, target.maximum):
            raise self.error(f'значение {interval.lo}…{interval.hi} не помещается в {target.c()}', node)
        if interval.within(target.minimum, target.maximum) and width.bits <= target.bits and (
                width.signed == target.signed or (not width.signed and target.bits > width.bits)):
            return f'(({target.c()}){value.code})'
        return f'P2C_TO_{target.key().upper()}({value.code})'

    def common_width(self, values: list[Value]) -> CInt:
        intervals = [self.interval_of(value) or self.width(value).interval() for value in values]
        if all(item.within(I16_RANGE.lo, I16_RANGE.hi) for item in intervals):
            return I16
        if all(item.within(U16_RANGE.lo, U16_RANGE.hi) for item in intervals):
            return U16
        return I32

    def arithmetic_width(self, result: Interval, operands: list[Value]) -> CInt:
        patterns = [self.interval_of(value) or self.width(value).interval() for value in operands]
        if all(item.within(BITS16_RANGE.lo, BITS16_RANGE.hi) for item in patterns):
            if result.within(I16_RANGE.lo, I16_RANGE.hi):
                return I16
            if result.within(U16_RANGE.lo, U16_RANGE.hi):
                return U16
        return I32

    @staticmethod
    def op_macro(width: CInt) -> str:
        return {'i16': 'P2C_I16', 'u16': 'P2C_U16'}.get(width.key(), 'P2C_I32')

    def int_const(self, number: int) -> Value:
        if not INT32_MIN <= number <= INT32_MAX:
            raise TranslationError(f'константа {number} вне int32')
        width = cint_for(Interval(number, number))
        suffix = 'L' if width.bits == 32 else ''
        if number == INT32_MIN:
            code = '(-2147483647L - 1)'
        else:
            code = f'{number}{suffix}'
        return Value(IntT(number, number), code, width, const=number)

    def bool_value(self, code: str, const: object = NO_CONST) -> Value:
        if const is NO_CONST and code in ('0', '1'):
            const = code == '1'
        t = BoolT(const) if isinstance(const, bool) else BOOL
        return Value(t, code, U8, const=const)

    # --- представление значений ------------------------------------------------

    def ctype(self, value: T) -> str:
        return self.r.ctype(value)

    def resolved(self, value: T, declared: T | None) -> T:
        """Форма ячейки для чтения: без потоков в строгом режиме — объявленная."""
        if isinstance(value, BottomT) and declared is not None and self.strict:
            value = declared
        return value

    def none_code(self, target: T) -> str:
        if isinstance(target, OptT):
            inner = target.inner
            if is_pointer(inner):
                return 'NULL'
            if isinstance(inner, FnT):
                return 'P2C_FN_NONE'
            if not self.emit:
                return 'p2c_none'
            # Временная структура: SDCC не переносит возврат структуры из вложенного вызова.
            result = self.temp(target)
            self.line(f'memset(&{result}, 0, sizeof {result});')
            return result
        raise self.error(f'None не помещается в {describe(target)}', None)

    def fn_make(self, fn_t: T, id_code: str, env_code: str) -> str:
        """Вызываемое значение во временной структуре (номер цели и окружение)."""
        if not self.emit:
            return 'p2c_fn'
        result = self.temp(fn_t)
        self.line(f'P2C_FN_SET({result}, {id_code}, {env_code});')
        return result

    def convert(self, value: Value, target: T, node: ast.AST) -> str:
        """Код значения в представлении ячейки формы target."""
        source = value.t
        if isinstance(target, BottomT) or isinstance(source, BottomT):
            if self.emit:
                raise self.unknown(node, 'преобразование')
            return value.code
        if isinstance(target, IntT):
            if not self.emit:
                return value.code
            return self.store_int(self.r.cint(target), value, node)
        if isinstance(target, BoolT):
            if isinstance(source, BoolT):
                return value.code
            if isinstance(source, IntT) and self.interval_of(value) and self.interval_of(value).within(0, 1):
                return f'((uint8_t){value.code})'
            raise self.error(f'ожидалось bool, есть {describe(source)}', node)
        if isinstance(target, OptT):
            if isinstance(source, NoneT):
                return self.none_code(target) if self.emit else '0'
            inner = target.inner
            if isinstance(source, OptT):
                if is_pointer(inner) or isinstance(inner, FnT):
                    return self.convert(Value(source.inner, value.code, value.cwidth), inner, node)
                if not self.emit or self.r.normalized(source) == self.r.normalized(target):
                    return value.code
                holder = self.temp(source)
                self.line(f'{holder} = {value.code};')
                result = self.temp(target)
                self.line(f'memset(&{result}, 0, sizeof {result});')
                self.line(f'if ({holder}.has) {{')
                self.indent += 1
                inner_code = self.convert(Value(source.inner, f'{holder}.v',
                                                self.r.cint(source.inner) if is_int_like(source.inner) else None),
                                          inner, node)
                self.line(f'{result}.has = 1; {result}.v = {inner_code};')
                self.indent -= 1
                self.line('}')
                return result
            if is_pointer(inner) or isinstance(inner, FnT):
                return self.convert(value, inner, node)
            if not self.emit:
                return value.code
            inner_code = self.convert(value, inner, node)
            result = self.temp(target)
            self.line(f'{result}.has = 1; {result}.v = {inner_code};')
            return result
        if isinstance(source, OptT) and not isinstance(target, OptT):
            # Чтение Optional там, где CPython требует значение: None здесь — отказ.
            if is_pointer(source.inner) or isinstance(source.inner, FnT):
                return self.convert(Value(source.inner, value.code, value.cwidth), target, node)
            return self.convert(Value(source.inner, f'P2C_UNWRAP({value.code})', None), target, node)
        if isinstance(target, TupleT):
            if not isinstance(source, TupleT) or len(source.items) != len(target.items):
                raise self.error(f'кортеж {describe(source)} вместо {describe(target)}', node)
            if not self.emit or self.r.normalized(source) == self.r.normalized(target):
                return value.code
            holder = self.temp(source)
            self.line(f'{holder} = {value.code};')
            result = self.temp(target)
            for index, (item_source, item_target) in enumerate(zip(source.items, target.items)):
                code = self.convert(Value(item_source, f'{holder}.v{index}', None), item_target, node)
                self.line(f'{result}.v{index} = {code};')
            return result
        if isinstance(target, ArrayT):
            if isinstance(source, ArrayT):
                if self.emit and self.r.normalized(source.elem) != self.r.normalized(target.elem):
                    return self.copy_array(value, target, node)
                return value.code
            if isinstance(source, TupleT):
                return self.tuple_to_array(value, target, node)
            raise self.error(f'{describe(source)} вместо {describe(target)}', node)
        if isinstance(target, (ListT, DequeT, SetT, DictT)):
            if isinstance(target, ListT) and isinstance(source, ArrayT):
                if self.emit and self.r.normalized(source.elem) != self.r.normalized(target.elem):
                    return self.copy_array(value, ArrayT(target.elem), node)
                return value.code
            if isinstance(target, ListT) and isinstance(source, TupleT):
                return self.tuple_to_array(value, ArrayT(target.elem), node)
            if type(source) is not type(target):
                if isinstance(target, ListT) and isinstance(source, ObjT) and self.p.list_base_of(source.cls) is not None:
                    return f'((P2cList *){value.code})'
                raise self.error(f'{describe(source)} вместо {describe(target)}', node)
            if self.emit and self.r.normalized(source) != self.r.normalized(target):
                raise self.error(f'контейнер {describe(source)} вместо {describe(target)}', node)
            return value.code
        if isinstance(target, ObjT):
            if not isinstance(source, ObjT):
                raise self.error(f'{describe(source)} вместо объекта {target.cls}', node)
            if not self.emit:
                return value.code
            if target.cls == '*' or source.cls == '*':
                return f'(({self.ctype(target)}){value.code})'
            if self.p.root(target.cls) != self.p.root(source.cls):
                raise self.error(f'объект {source.cls} вместо {target.cls}', node)
            return value.code
        if isinstance(target, ValT):
            if not isinstance(source, ValT) or source.cls != target.cls:
                raise self.error(f'{describe(source)} вместо {describe(target)}', node)
            return value.code
        if isinstance(target, FnT):
            if not isinstance(source, FnT):
                raise self.error(f'{describe(source)} вместо вызываемого значения', node)
            return value.code
        if isinstance(target, BytesT):
            if not isinstance(source, BytesT):
                raise self.error(f'{describe(source)} вместо bytes', node)
            return value.code
        if isinstance(target, (StrT, ImageT, TargetT, FontT)):
            if type(source) is not type(target):
                raise self.error(f'{describe(source)} вместо {describe(target)}', node)
            return value.code
        if isinstance(target, ExtT):
            # Объект платформы (P2cHandle) передаётся как есть; класс должен совпадать.
            if not isinstance(source, ExtT) or source.name != target.name:
                raise self.error(f'{describe(source)} вместо {describe(target)}', node)
            return value.code
        if isinstance(target, VoidT):
            return value.code
        if isinstance(target, NoneT) and isinstance(source, NoneT):
            return '0'
        raise self.error(f'нельзя преобразовать {describe(source)} в {describe(target)}', node)

    def zero_code(self, value: T) -> str:
        if is_int_like(value):
            return '0'
        if is_pointer(value):
            return 'NULL'
        if isinstance(value, FnT):
            return 'P2C_FN_NONE'
        if isinstance(value, OptT):
            return self.none_code(value)
        return f'p2c_zero_{self.ctype(value).replace(" ", "").replace("*", "p")}'

    def tuple_to_array(self, value: Value, target: ArrayT, node: ast.AST) -> str:
        source = value.t
        if not self.emit:
            return value.code
        holder = self.temp(source)
        self.line(f'{holder} = {value.code};')
        result = self.temp(target)
        element_c = self.ctype(target.elem)
        self.line(f'{result} = p2c_array_new({self.container_class(target)}, sizeof({element_c}), '
                  f'{len(source.items)});')
        self.plan.allocates = True
        for index, item in enumerate(source.items):
            code = self.convert(Value(item, f'{holder}.v{index}', None), target.elem, node)
            self.line(f'P2C_PUT({result}, {element_c}, {index}, {code});')
        return result

    def copy_array(self, value: Value, target: ArrayT, node: ast.AST) -> str:
        source = value.t
        holder = self.temp(source)
        self.line(f'{holder} = {value.code};')
        result = self.temp(target)
        element_c = self.ctype(target.elem)
        index = self.temp(U16)
        self.line(f'{result} = p2c_array_new({self.container_class(target)}, sizeof({element_c}), {holder}->length);')
        self.plan.allocates = True
        self.line(f'for ({index} = 0; {index} < {holder}->length; {index}++) {{')
        self.indent += 1
        element = Value(source.elem, f'P2C_AT({holder}, {self.ctype(source.elem)}, {index})',
                        self.r.cint(source.elem) if is_int_like(source.elem) else None)
        code = self.convert(element, target.elem, node)
        self.line(f'P2C_PUT({result}, {element_c}, {index}, {code});')
        self.indent -= 1
        self.line('}')
        return result

    def container_class(self, value: T) -> str:
        """Номер класса кучи для контейнера (разметка сборщика по элементам)."""
        if not self.emit:
            return '0'
        return self.c.layout.container_class_symbol(value)

    def truth(self, value: Value, node: ast.AST) -> str:
        """C-условие истинности значения по правилам CPython."""
        t = value.t
        if self.incomplete(t):
            raise self.unknown(node)
        if isinstance(t, BoolT):
            # Все потоки ячейки дают одно значение: условие постоянно (мёртвая ветвь не транслируется).
            if t.value is not None:
                return '1' if t.value else '0'
            return value.code
        if isinstance(t, IntT):
            if t.lo == t.hi and not int_empty(t):
                return '1' if t.lo != 0 else '0'
            return f'({value.code} != 0)'
        if isinstance(t, NoneT):
            return '0'
        if isinstance(t, OptT):
            inner = t.inner
            if is_pointer(inner):
                if isinstance(inner, ObjT):
                    return f'({value.code} != NULL)'
                return f'P2C_TRUTH_OPT_LEN({value.code})'
            if isinstance(inner, FnT):
                return f'({value.code}.id != 0)'
            holder = value.code
            if self.emit and not self.stable(holder):
                holder = self.temp(t)
                self.line(f'{holder} = {value.code};')
            inner_truth = self.truth(Value(inner, f'{holder}.v', None), node)
            return f'({holder}.has && {inner_truth})'
        if isinstance(t, (ListT, ArrayT, DequeT, DictT, SetT, BytesT, StrT)):
            return f'({value.code}->length != 0)'
        if isinstance(t, TupleT):
            return '1' if t.items else '0'
        if isinstance(t, ObjT):
            if t.cls != '*' and self.p.list_base_of(t.cls) is not None:
                return f'(((P2cList *){value.code})->length != 0)'
            return '1'
        if isinstance(t, (FnT, ValT, ImageT)):
            return '1'
        raise self.error(f'истинность {describe(t)} не поддержана', node)

    # --- порядок вычислений -----------------------------------------------------

    @staticmethod
    def stable(code: str) -> bool:
        """Код не читает изменяемое состояние: литерал, локальная или временная."""
        stripped = code.strip()
        while stripped.startswith('(') and stripped.endswith(')'):
            inner = stripped[1:-1]
            depth = 0
            balanced = True
            for char in inner:
                if char == '(':
                    depth += 1
                elif char == ')':
                    depth -= 1
                    if depth < 0:
                        balanced = False
                        break
            if not balanced or depth:
                break
            stripped = inner.strip()
        for prefix in ('(int32_t)', '(int16_t)', '(uint16_t)', '(uint8_t)', '(int8_t)'):
            if stripped.startswith(prefix):
                stripped = stripped[len(prefix):].strip('()')
        if stripped in ('NULL', 'P2C_FN_NONE'):
            return True
        return stripped.replace('_', 'a').isalnum() or stripped.rstrip('L').lstrip('-').isdigit()

    def fix_left(self, earlier: list[Value], mark: int) -> None:
        """Позднее подвыражение породило строки: ранние чтения копируются перед ними."""
        if not self.emit or len(self.lines) == mark:
            return
        inserted = []
        for value in earlier:
            if not value.code or self.stable(value.code) or isinstance(value.t, (VoidT, BottomT)):
                continue
            if value.meta is not None and not value.code:
                continue
            value_type = value.t
            name = self.temp(value_type)
            if value.cwidth is not None and is_int_like(value_type):
                self.plan.temps[name] = ('cint', value.cwidth)
            inserted.append('    ' * self.indent + f'{name} = {value.code};')
            value.code = name
        self.lines[mark:mark] = inserted

    def hoist(self, value: Value) -> Value:
        """Значение во временной переменной (однократное вычисление)."""
        if not self.emit or self.stable(value.code) or isinstance(value.t, VoidT):
            return value
        name = self.temp(value.t)
        if value.cwidth is not None and is_int_like(value.t):
            self.plan.temps[name] = ('cint', value.cwidth)
        self.line(f'{name} = {value.code};')
        return Value(value.t, name, value.cwidth, value.path, value.const, value.meta)

    # --- сужение Optional по условиям ------------------------------------------------

    def narrowed(self, value: Value) -> Value:
        """Значение пути, доказанно не None, читается как внутренняя форма."""
        if value.path is None or value.path not in self.present or not isinstance(value.t, OptT):
            return value
        inner = value.t.inner
        code = value.code if (is_pointer(inner) or isinstance(inner, FnT)) else f'P2C_UNWRAP({value.code})'
        result = Value(inner, code, None, value.path, value.const, value.meta, value.cell)
        if self.emit and is_int_like(inner):
            result.cwidth = self.r.cint(inner)
        return result

    @staticmethod
    def path_text(node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            owner = EmitterBase.path_text(node.value)
            return None if owner is None else f'{owner}.{node.attr}'
        return None

    def narrowing(self, node: ast.expr, truth: bool) -> set[str]:
        """Пути, не равные None при данном значении условия."""
        if isinstance(node, ast.BoolOp):
            result: set[str] = set()
            if (truth and isinstance(node.op, ast.And)) or (not truth and isinstance(node.op, ast.Or)):
                for item in node.values:
                    result |= self.narrowing(item, truth)
            return result
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self.narrowing(node.operand, not truth)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            op = node.ops[0]
            right = node.comparators[0]
            if isinstance(right, ast.Constant) and right.value is None:
                path = self.path_text(node.left)
                if path is not None:
                    if isinstance(op, ast.IsNot) and truth:
                        return {path}
                    if isinstance(op, ast.Is) and not truth:
                        return {path}
            return set()
        if truth:
            path = self.path_text(node)
            if path is not None:
                return {path}
        return set()

    def kill_present(self, path: str) -> None:
        self.present = {item for item in self.present if item != path and not item.startswith(path + '.')}

    def kill_assigned_in(self, nodes: list) -> None:
        """Перед циклом: факты о путях, изменяемых в теле, не действуют."""
        for statement in nodes:
            for part in ast.walk(statement):
                if isinstance(part, (ast.Name, ast.Attribute)) and isinstance(part.ctx, (ast.Store, ast.Del)):
                    path = self.path_text(part)
                    if path is not None:
                        self.kill_present(path)

    # --- уточнения интервалов по условиям ----------------------------------------

    def refined(self, key: str, interval: Interval | None) -> Interval | None:
        for scope in self.refinements:
            refinement = scope.get(key)
            if refinement is not None:
                if interval is None:
                    interval = refinement
                else:
                    narrowed = interval.intersect(refinement)
                    interval = narrowed if narrowed is not None else interval
        return interval

    def kill_refinement(self, key: str) -> None:
        for scope in self.refinements:
            scope.pop(key, None)

    def condition_refinements(self, node: ast.expr, truth: bool) -> dict[str, Interval]:
        result: dict[str, Interval] = {}
        if isinstance(node, ast.BoolOp):
            if (truth and isinstance(node.op, ast.And)) or (not truth and isinstance(node.op, ast.Or)):
                for item in node.values:
                    for key, interval in self.condition_refinements(item, truth).items():
                        current = result.get(key)
                        merged = interval if current is None else current.intersect(interval)
                        if merged is not None:
                            result[key] = merged
            return result
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return self.condition_refinements(node.operand, not truth)
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            op = type(node.ops[0]).__name__
            if op not in COMPARE_SYMBOLS:
                return result
            if not truth:
                op = NEGATED[op]
                if op == 'NotEq':
                    return result
            left, right = node.left, node.comparators[0]
            for name_node, other_node, operator in ((left, right, op), (right, left, SWAPPED[op])):
                if isinstance(name_node, ast.Name) and self.is_local(name_node.id):
                    other = self.static_interval(other_node)
                    if other is None:
                        continue
                    key = self.local_key(name_node.id)
                    base = self.local_interval(name_node.id) or TOP
                    refined = refine_compare(operator, base, other)
                    if refined is not None:
                        result[key] = refined
        return result

    def static_interval(self, node: ast.expr) -> Interval | None:
        """Интервал выражения без эффектов: константы, локальные, модульные целые."""
        if isinstance(node, ast.Constant) and type(node.value) is int:
            return Interval.of(node.value)
        if isinstance(node, ast.Constant) and type(node.value) is bool:
            return Interval.of(int(node.value))
        if isinstance(node, ast.Name):
            if self.is_local(node.id):
                return self.refined(self.local_key(node.id), self.local_interval(node.id))
            value = getattr(self.module, node.id, None)
            if type(value) is int:
                return Interval.of(value)
            return None
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            inner = self.static_interval(node.operand)
            return None if inner is None else Interval(-inner.hi, -inner.lo)
        if isinstance(node, ast.BinOp):
            from .intervals import binary
            left = self.static_interval(node.left)
            right = self.static_interval(node.right)
            if left is None or right is None:
                return None
            constant = node.right.value if isinstance(node.right, ast.Constant) else None
            return binary(type(node.op).__name__, left, right, constant)
        return None

    # --- имена -----------------------------------------------------------------

    def local_key(self, name: str) -> str:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return name

    def is_local(self, name: str) -> bool:
        for scope in self.scopes:
            if name in scope:
                return True
        return name in self.param_names or name in self.assigned

    def local_interval(self, name: str) -> Interval | None:
        key = self.local_key(name)
        if key in self.param_names and not any(name in scope for scope in self.scopes):
            param = self.param(name)
            t = self.resolved(param.t, param.declared)
        else:
            t = self.plan.locals.get(key, BOTTOM)
        if isinstance(t, BoolT):
            return BOOL_RANGE
        if isinstance(t, IntT):
            if int_empty(t):
                return TOP if self.strict else None
            return t.interval
        return None

    def param(self, name: str):
        for param in self.plan.params:
            if param.name == name:
                return param
        raise KeyError(name)

    def module_global(self, name: str) -> tuple[bool, object]:
        if hasattr(self.module, name):
            return True, getattr(self.module, name)
        return False, None

    def builtin_exists(self, name: str) -> bool:
        return hasattr(builtins, name)

    def branch_assign(self, condition: str, result: str, then_code, else_code) -> None:
        """if/else с присваиванием; строки преобразований попадают внутрь своей ветви."""
        self.line(f'if ({condition}) {{')
        self.indent += 1
        self.line(f'{result} = {then_code()};')
        self.indent -= 1
        self.line('} else {')
        self.indent += 1
        self.line(f'{result} = {else_code()};')
        self.indent -= 1
        self.line('}')

    def note_flow(self, value: Value, cell_t: T) -> None:
        """Анализ: дисплей или включение попадает в ячейку — строить его с формой ячейки."""
        if self.emit or value.display is None or isinstance(cell_t, BottomT):
            return
        if not isinstance(cell_t, (ListT, ArrayT, DictT, SetT, DequeT)):
            if isinstance(cell_t, OptT) and isinstance(cell_t.inner, (ListT, ArrayT, DictT, SetT, DequeT)):
                cell_t = cell_t.inner
            else:
                return
        key = id(value.display)
        previous = self.c.display_types.get(key)
        merged = cell_t if previous is None else self.c.join(previous, cell_t)
        if merged != previous:
            self.c.display_types[key] = merged
            self.c.display_nodes[key] = value.display
            self.c.changed = True

    def incomplete(self, t: T) -> bool:
        """Форма ещё может вырасти: нет потоков или пока известен только None (анализ)."""
        return isinstance(t, BottomT) or (isinstance(t, NoneT) and not self.emit)
