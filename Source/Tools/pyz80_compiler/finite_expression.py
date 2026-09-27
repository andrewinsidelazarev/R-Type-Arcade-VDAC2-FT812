"""Табулирование чистого выражения Python по конечному целому аргументу."""
import ast
import copy
import hashlib
import struct


def tabulate_i32(expression,variable,stop,constants):
    """Полное перечисление [0, stop); вне указанного домена подмена запрещена."""
    if not 0<stop<=65536: raise ValueError('Аргумент таблицы должен помещаться в u16')
    class Bind(ast.NodeTransformer):
        def visit(self,node):
            if ast.unparse(node)==variable:
                return ast.copy_location(ast.Name(id='_argument',ctx=ast.Load()),node)
            return super().visit(node)
        def visit_Name(self,node):
            if node.id in constants:
                return ast.copy_location(ast.Constant(value=constants[node.id]),node)
            return node
    bound=Bind().visit(copy.deepcopy(expression))
    allowed=(ast.Expression,ast.Constant,ast.Name,ast.Load,ast.BinOp,ast.UnaryOp,ast.Call,
             ast.Add,ast.Sub,ast.Mult,ast.Div,ast.FloorDiv,ast.BitAnd,ast.BitOr,ast.BitXor,
             ast.LShift,ast.RShift,ast.USub,ast.UAdd)
    for node in ast.walk(bound):
        if not isinstance(node,allowed): raise ValueError('Нечистый узел таблицы: '+ast.dump(node))
        if isinstance(node,ast.Name) and node.id not in ('_argument','round'):
            raise ValueError('Несвязанный вход таблицы: '+node.id)
        if isinstance(node,ast.Call) and (not isinstance(node.func,ast.Name) or node.func.id!='round' or node.keywords):
            raise ValueError('В таблице разрешён только чистый round')
    program=compile(ast.fix_missing_locations(ast.Expression(bound)),'<конечная таблица Python>','eval')
    data=bytearray(); minimum=maximum=None
    for value in range(stop):
        answer=eval(program,{'__builtins__':{},'round':round},{'_argument':value})
        if type(answer) is not int or not -2147483648<=answer<=2147483647:
            raise ValueError(f'Значение таблицы не представимо как i32: {value} -> {answer}')
        minimum=answer if minimum is None else min(minimum,answer)
        maximum=answer if maximum is None else max(maximum,answer)
        data.extend(struct.pack('<i',answer))
    return bytes(data),dict(expression=ast.unparse(expression),argument=variable,
        first=0,stop=stop,entries=stop,minimum=minimum,maximum=maximum,
        sha256=hashlib.sha256(data).hexdigest())
