"""Выполнить ресурсный конструктор без импорта игрового модуля и внешнего I/O."""
import __future__
import ast
import builtins
import copy
import hashlib
import struct


class FrozenResource:
    def __init__(self,data):
        if type(data) is not bytes: raise ValueError('Ресурс должен быть bytes')
        self.data=data

    def read_bytes(self):
        return self.data


def freeze_constructor(source,owner,*,resources,fields):
    tree=ast.parse(source)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==owner)
    if cls.bases or cls.decorator_list: raise ValueError('Конструктор требует простого класса')
    methods={n.name:n for n in cls.body if isinstance(n,ast.FunctionDef)}
    selected=set();active=set()
    allowed={'range','len','bytearray','bool','int','ValueError','struct.pack_into','struct.unpack_from'}
    allowed.update(name+'.read_bytes' for name in resources)
    def visit(name):
        if name in active: raise ValueError('Рекурсия в конструкторе не доказана')
        if name in selected: return
        active.add(name)
        for node in ast.walk(methods[name]):
            if isinstance(node,(ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal,ast.While,ast.With,ast.Try)):
                raise ValueError('Неподдержанный эффект/цикл в ресурсном конструкторе')
            if isinstance(node,ast.Call):
                call=ast.unparse(node.func)
                if call.startswith('self.') and call[5:] in methods: visit(call[5:])
                elif call not in allowed: raise ValueError('Не связан вызов конструктора: '+call)
            if isinstance(node,ast.Attribute) and node.attr.startswith('__'):
                raise ValueError('Динамическое обращение к Python runtime запрещено')
        active.remove(name);selected.add(name)
    visit('__init__')
    frozen=copy.deepcopy(cls)
    frozen.body=[node for node in frozen.body if isinstance(node,ast.FunctionDef) and node.name in selected]
    def finite_range(*args):
        values=range(*args)
        if len(values)>65536: raise ValueError('Ресурсный цикл превышает конечный бюджет')
        return values
    def allocate(size):
        if type(size) is not int or not 0<=size<=0x400000: raise ValueError('Не связан размер bytearray')
        return bytearray(size)
    namespace={'__builtins__':{'__build_class__':builtins.__build_class__},'__name__':'frozen_constructor',
               'range':finite_range,'len':len,'bytearray':allocate,'bool':bool,'int':int,'ValueError':ValueError,'struct':struct,
               **{name:FrozenResource(data) for name,data in resources.items()}}
    exec(compile(ast.Module(body=[frozen],type_ignores=[]),'<frozen-constructor>','exec',
                 flags=__future__.annotations.compiler_flag),namespace)
    def snapshot():
        instance=namespace[owner]()
        if set(vars(instance))!=set(fields): raise ValueError('Схема не покрывает все поля конструктора')
        result={}
        for name,kind in fields.items():
            value=getattr(instance,name)
            if isinstance(kind,int):
                if type(value) is not list or len(value)!=kind or any(type(x) is not int or not -2**31<=x<2**31 for x in value):
                    raise ValueError('Не совпадает целочисленный массив '+name)
                result[name]=tuple(value)
            elif kind=='bytes' and type(value) is bytes: result[name]=value
            elif kind=='list[bytearray]' and type(value) is list and all(type(x) is bytearray for x in value):
                if len({id(x) for x in value})!=len(value): raise ValueError('Совместное владение буфером не связано')
                result[name]=tuple(bytes(x) for x in value)
            else: raise ValueError('Не совпадает тип поля '+name)
        return result
    first=snapshot()
    if first!=snapshot(): raise ValueError('Результат конструктора непостоянен')
    return first,dict(resource_sha256={name:hashlib.sha256(data).hexdigest() for name,data in resources.items()},
        method_ast_sha256={name:hashlib.sha256(ast.dump(methods[name]).encode()).hexdigest() for name in sorted(selected)},
        runtime_io=False,source_module_imported=False,complete_constructor=True)
