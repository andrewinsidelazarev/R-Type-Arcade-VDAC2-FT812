"""Ограниченное понижение AST для отдельной интерактивной демонстрации.

Не заменяет объектную VM. Неподдержанные узлы вызывают ошибку, а исключённые
подсистемы перечисляются вызывающим профилем и попадают в отчёт сборки.
"""
from __future__ import annotations

import ast


class ScalarRecordEmitter:
    """Статические записи, целые i32, ветвления и ограниченные циклы Python."""

    def __init__(self, constants, aliases=None, calls=None):
        self.constants = constants
        self.aliases = aliases or {}
        self.calls = calls or {}
        self.locals = set()

    def expr(self, n):
        key = ast.unparse(n)
        if key in self.aliases:
            return self.aliases[key]
        if isinstance(n, ast.Constant):
            if n.value is None:
                return '0'
            if isinstance(n.value, (bool, int)):
                return f"{int(n.value)}L"
            raise ValueError(f"Неподдержанный литерал: {key}")
        if isinstance(n, ast.Name):
            if n.id in self.constants:
                value = self.constants[n.id]
                if not isinstance(value, (bool, int)):
                    raise ValueError(f"Не скаляр: {n.id}")
                return f"{int(value)}L"
            return n.id
        if isinstance(n, ast.Attribute):
            return self.expr(n.value) + "->" + n.attr
        if isinstance(n, ast.BinOp):
            a, b = self.expr(n.left), self.expr(n.right)
            if isinstance(n.op, ast.FloorDiv):
                divisor=(n.right.value if isinstance(n.right,ast.Constant) else
                         self.constants.get(n.right.id) if isinstance(n.right,ast.Name) else None)
                if isinstance(divisor,int) and 0<divisor<=0x40000000 and divisor&(divisor-1)==0:
                    # SDCC/Z80: ASR знакового i32 округляет вниз, включая отрицательные числа.
                    return f"((int32_t)({a}) >> {divisor.bit_length()-1}) /* ASR: деление вниз на {divisor}. */"
                return f"py_floor({a}, {b})"
            ops = {ast.Add: '+', ast.Sub: '-', ast.Mult: '*', ast.BitAnd: '&',
                   ast.BitOr: '|', ast.BitXor: '^', ast.LShift: '<<', ast.RShift: '>>'}
            if type(n.op) not in ops:
                raise ValueError(f"Неподдержанная арифметика: {key}")
            return f"({a} {ops[type(n.op)]} {b})"
        if isinstance(n, ast.UnaryOp):
            return "(" + {ast.Not:'!', ast.USub:'-', ast.Invert:'~', ast.UAdd:'+'}[type(n.op)] + self.expr(n.operand) + ")"
        if isinstance(n, ast.BoolOp):
            return '(' + (' && ' if isinstance(n.op, ast.And) else ' || ').join(self.expr(v) for v in n.values) + ')'
        if isinstance(n, ast.Compare):
            ops = {ast.Eq:'==', ast.NotEq:'!=', ast.Lt:'<', ast.LtE:'<=', ast.Gt:'>', ast.GtE:'>=', ast.Is:'==', ast.IsNot:'!='}
            values = [n.left, *n.comparators]
            return '(' + ' && '.join(f"({self.expr(a)} {ops[type(op)]} {self.expr(b)})"
                                      for a, op, b in zip(values, n.ops, values[1:])) + ')'
        if isinstance(n, ast.IfExp):
            return f"({self.expr(n.test)} ? {self.expr(n.body)} : {self.expr(n.orelse)})"
        if isinstance(n, ast.Call):
            name = ast.unparse(n.func)
            if name in self.calls:
                return self.calls[name](n, self)
            if name in ('min', 'max', 'int', 'bool'):
                name = {'min':'py_min', 'max':'py_max', 'int':'py_int', 'bool':'py_bool'}[name]
            elif name not in ('advance_pitch', 'advance_wave_charge', 'wave_power', 'wave_power_tier', 'beam_animation_phase', '_u16'):
                raise ValueError(f"Не зарегистрирован вызов: {key}")
            if n.keywords:
                raise ValueError(f"Не зарегистрирован именованный вызов: {key}")
            return name + '(' + ', '.join(self.expr(a) for a in n.args) + ')'
        raise ValueError(f"Неподдержанное выражение {type(n).__name__}: {key}")

    def statements(self, nodes, indent='    '):
        lines = []
        for n in nodes:
            if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                continue
            lines.append(f"{indent}/* Python: строка {n.lineno}; {type(n).__name__}. */")
            if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                targets = n.targets if isinstance(n, ast.Assign) else [n.target]
                if len(targets) != 1 or isinstance(targets[0], (ast.Tuple, ast.List)):
                    raise ValueError('Неподдержанное распаковывание')
                target = targets[0]
                if isinstance(target, ast.Name):
                    self.locals.add(target.id)
                destination = self.expr(target)
                rhs = n.value
                if isinstance(n, ast.AugAssign):
                    rhs = ast.BinOp(left=target, op=n.op, right=n.value)
                lines.append(f"{indent}{destination} = {self.expr(rhs)}; /* Вычислить, затем записать. */")
            elif isinstance(n, ast.If):
                lines.append(f"{indent}if ({self.expr(n.test)}) {{")
                lines += self.statements(n.body, indent + '    ')
                if n.orelse:
                    lines.append(f"{indent}}} else {{")
                    lines += self.statements(n.orelse, indent + '    ')
                lines.append(indent + '}')
            elif isinstance(n, ast.While):
                if n.orelse:
                    raise ValueError('while/else не поддержан')
                lines.append(f"{indent}while ({self.expr(n.test)}) {{")
                lines.append(f"{indent}    if (!fuel--) {{ demo_fault = 1; return 1; }}")
                lines += self.statements(n.body, indent + '    ')
                lines.append(indent + '}')
            elif isinstance(n, ast.For):
                if (n.orelse or not isinstance(n.target, ast.Name) or
                    not isinstance(n.iter, ast.Call) or ast.unparse(n.iter.func) != 'range' or
                    len(n.iter.args) != 1 or not isinstance(n.iter.args[0], ast.Constant) or
                    not 0 <= n.iter.args[0].value <= 256):
                    raise ValueError('Не доказана граница цикла for')
                self.locals.add(n.target.id)
                lines.append(f"{indent}for ({n.target.id}=0; {n.target.id}<{n.iter.args[0].value}; ++{n.target.id}) {{")
                lines += self.statements(n.body, indent + '    ')
                lines.append(indent + '}')
            elif isinstance(n, ast.Return):
                lines.append(f"{indent}return{(' ' + self.expr(n.value)) if n.value is not None else ''};")
            elif isinstance(n, ast.Continue):
                lines.append(indent + 'continue;')
            elif isinstance(n, ast.Expr):
                lines.append(indent + self.expr(n.value) + ';')
            else:
                raise ValueError(f"Неподдержанная инструкция {type(n).__name__}: {ast.unparse(n)}")
        return lines

    def function(self, signature, nodes, parameters=(), prefix=()):
        self.locals = set()
        lines = self.statements(nodes)
        declarations = [f"    int32_t {v};" for v in sorted(self.locals - set(parameters))]
        return '\n'.join([signature + ' {', *declarations, *prefix, *lines, '}']) + '\n'


def retain_writes(nodes, fields):
    """Явная проекция эффектов; условия и порядок сохраняются, вызовы исключены."""
    result = []
    for node in nodes:
        if isinstance(node, ast.If):
            body = retain_writes(node.body, fields)
            other = retain_writes(node.orelse, fields)
            if body or other:
                copy = ast.If(test=node.test, body=body, orelse=other)
                ast.copy_location(copy, node)
                result.append(copy)
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(ast.unparse(t) in fields for t in targets):
                result.append(node)
    return result
