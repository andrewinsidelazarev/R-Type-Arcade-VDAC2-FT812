"""Полное понижение скалярного dataclass в C, без выборочной проекции эффектов.

Поддерживаются int/bool, помеченные int|None, свойства, статические и обычные
методы, чистые конечные множества. Неизвестные конструкции отвергаются.
Объектный граф игры и динамические контейнеры остаются задачей общей VM.
"""
from __future__ import annotations
import ast
import copy
import hashlib
from dataclasses import dataclass

from .demo_projection import ScalarRecordEmitter
from .frontend import _safe_constant


def constant(node,values):
    if isinstance(node,ast.Set): return frozenset(constant(x,values) for x in node.elts)
    if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='frozenset' and len(node.args)==1 and not node.keywords:
        source=node.args[0]
        if isinstance(source,ast.GeneratorExp):
            if len(source.generators)!=1: raise ValueError('Вложенная генерация констант не поддержана')
            generator=source.generators[0]
            if generator.ifs or generator.is_async or not isinstance(generator.target,ast.Name):
                raise ValueError('Не доказан конечный генератор констант')
            items=constant(generator.iter,values)
            if not isinstance(items,(tuple,list,frozenset)) or len(items)>4096:
                raise ValueError('Слишком большой домен константы')
            return frozenset(constant(source.elt,{**values,generator.target.id:value}) for value in items)
        return frozenset(constant(source,values))
    if isinstance(node,ast.BinOp) and isinstance(node.op,ast.BitOr):
        return constant(node.left,values)|constant(node.right,values)
    return _safe_constant(node,values)


@dataclass
class RecordArtifact:
    header:str
    code:str
    manifest:dict


class RecordEmitter(ScalarRecordEmitter):
    def __init__(self,constants,fields,methods,prefix):
        super().__init__(constants,{'self':'record'})
        self.fields=fields; self.methods=methods; self.prefix=prefix
        self.optional={}; self.nonnull=set(); self.sets={}
        self.boolean_names=set()
        self.pure_methods=set(); self.effect_root=None

    def optional_reference(self,n):
        return self.optional.get(ast.unparse(n))

    def expr(self,n):
        reference=self.optional_reference(n)
        if reference:
            if ast.unparse(n) not in self.nonnull:
                raise ValueError('Чтение int|None без доказательства is not None: '+ast.unparse(n))
            return reference+'.value'
        if isinstance(n,ast.Constant) and n.value is None:
            raise ValueError('None не является числовым нулём')
        if isinstance(n,ast.BoolOp):
            def boolean(value):
                return (ast.unparse(value) in self.boolean_names or isinstance(value,ast.Compare) or
                        isinstance(value,ast.Constant) and type(value.value) is bool or
                        isinstance(value,ast.UnaryOp) and isinstance(value.op,ast.Not) or
                        isinstance(value,ast.BoolOp) and all(boolean(v) for v in value.values))
            if not all(boolean(v) for v in n.values):
                raise ValueError('and/or с не-bool операндами требует сохранения значения, не логического C-оператора')
        if isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name) and n.value.id=='self':
            if n.attr in self.fields: return 'record->'+n.attr
            if n.attr in self.methods and self.methods[n.attr][1]=='property':
                return self.prefix+'_'+n.attr+'(record)'
            raise ValueError('Неизвестное поле/свойство: '+ast.unparse(n))
        if isinstance(n,ast.Compare) and len(n.ops)==1:
            other=n.comparators[0]
            if isinstance(n.ops[0],(ast.Is,ast.IsNot)) and isinstance(other,ast.Constant) and other.value is None:
                reference=self.optional_reference(n.left)
                if not reference: raise ValueError('is None требует помеченного optional')
                return ('!' if isinstance(n.ops[0],ast.Is) else '')+reference+'.present'
            if isinstance(n.ops[0],(ast.In,ast.NotIn)):
                members=constant(other,self.constants)
                if not isinstance(members,frozenset) or any(type(x) is not int or not -2147483648<=x<=2147483647 for x in members):
                    raise ValueError('Нужен конечный набор i32 для membership')
                key=tuple(sorted(members))
                index=self.sets.setdefault(key,len(self.sets))
                call=f'{self.prefix}_set_{index}({self.expr(n.left)})'
                return '!'+call if isinstance(n.ops[0],ast.NotIn) else call
            if isinstance(n.ops[0],(ast.Is,ast.IsNot)):
                raise ValueError('Идентичность скаляров вне None не заменяется равенством')
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and ast.unparse(n.func.value)=='self':
            method=self.methods.get(n.func.attr)
            if not method or method[1]=='property' or n.keywords:
                raise ValueError('Не связан вызов метода: '+ast.unparse(n))
            if n.func.attr not in self.pure_methods and n is not self.effect_root:
                raise ValueError('Вложенный вызов с эффектами требует последовательного IR')
            args=[] if method[1]=='staticmethod' else ['record']
            parameters=method[0].args.args[(0 if method[1]=='staticmethod' else 1):]
            if len(parameters)!=len(n.args): raise ValueError('Не совпадает число аргументов метода')
            for parameter,value in zip(parameters,n.args):
                if ast.unparse(parameter.annotation)=='int | None':
                    reference=self.optional_reference(value)
                    if not reference: raise ValueError('Nullable-вызов требует помеченный аргумент')
                    args.append('&('+reference+')')
                else: args.append(self.expr(value))
            return self.prefix+'_'+n.func.attr+'('+', '.join(args)+')'
        if isinstance(n,ast.Call) and (not isinstance(n.func,ast.Name) or n.func.id not in ('min','max','int','bool')):
            raise ValueError('Внешний вызов записи не связан: '+ast.unparse(n.func))
        return super().expr(n)

    def statements(self,nodes,indent='    '):
        lines=[]
        for node in nodes:
            if isinstance(node,(ast.For,ast.While)):
                raise ValueError('Цикл записи требует отдельного доказательства границы и бюджета')
            if isinstance(node,ast.If):
                condition=self.expr(node.test)
                positive=negative=None
                test=node.test
                if isinstance(test,ast.Compare) and len(test.ops)==1 and isinstance(test.ops[0],(ast.Is,ast.IsNot)) and isinstance(test.comparators[0],ast.Constant) and test.comparators[0].value is None:
                    if isinstance(test.ops[0],ast.IsNot): positive=ast.unparse(test.left)
                    else: negative=ast.unparse(test.left)
                previous=set(self.nonnull)
                if positive: self.nonnull.add(positive)
                body=self.statements(node.body,indent+'    ')
                body_nonnull=set(self.nonnull)
                self.nonnull=set(previous)
                if negative: self.nonnull.add(negative)
                other=self.statements(node.orelse,indent+'    ')
                self.nonnull=body_nonnull&self.nonnull
                lines += [f'{indent}/* Python: строка {node.lineno}; If. */',f'{indent}if ({condition}) {{',*body]
                if node.orelse: lines += [indent+'} else {',*other]
                lines += [indent+'}']
                continue
            if isinstance(node,(ast.Assign,ast.AnnAssign)):
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                if len(targets)==1 and (destination:=self.optional_reference(targets[0])):
                    lines.append(f'{indent}/* Python: строка {node.lineno}; помеченное int|None. */')
                    value=node.value
                    if isinstance(value,ast.Constant) and value.value is None:
                        lines += [f'{indent}{destination}.present=0;',f'{indent}{destination}.value=0;']
                        self.nonnull.discard(ast.unparse(targets[0]))
                    elif reference:=self.optional_reference(value):
                        lines.append(f'{indent}{destination}={reference};')
                        self.nonnull.discard(ast.unparse(targets[0]))
                    else:
                        lines += [f'{indent}{destination}.value={self.expr(value)};',f'{indent}{destination}.present=1;']
                        self.nonnull.add(ast.unparse(targets[0]))
                    continue
            previous_root=self.effect_root
            if isinstance(node,(ast.Assign,ast.AnnAssign,ast.Expr)) and isinstance(node.value,ast.Call):
                self.effect_root=node.value
            lines+=super().statements([node],indent)
            self.effect_root=previous_root
        return lines


def compile_record(source,class_name,prefix=None):
    prefix=prefix or class_name
    tree=ast.parse(source)
    owner=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==class_name)
    if owner.bases or [ast.unparse(d) for d in owner.decorator_list]!=['dataclass']:
        raise ValueError('Нужен простой @dataclass без наследования')
    constants={}
    for n in tree.body:
        if isinstance(n,(ast.Assign,ast.AnnAssign)):
            targets=n.targets if isinstance(n,ast.Assign) else [n.target]
            if len(targets)==1 and isinstance(targets[0],ast.Name) and n.value is not None:
                try: constants[targets[0].id]=constant(n.value,constants)
                except (ValueError,TypeError,ArithmeticError): pass
    def annotation(node):
        text=ast.unparse(node) if node is not None else None
        if text in ('int','bool'): return 'int32_t'
        if text=='int | None': return 'PyRecordMaybeI32'
        if text=='None': return 'void'
        raise ValueError('Неподдержанный тип записи: '+str(text))
    fields={}; defaults={}; methods={}
    for n in owner.body:
        if isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str): continue
        if isinstance(n,ast.AnnAssign) and isinstance(n.target,ast.Name):
            fields[n.target.id]=annotation(n.annotation)
            if fields[n.target.id]=='void' or n.value is None: raise ValueError('Поле без скалярного default')
            defaults[n.target.id]=n.value
        elif isinstance(n,ast.FunctionDef):
            decorators=[ast.unparse(d) for d in n.decorator_list]
            if decorators not in ([],['property'],['staticmethod']): raise ValueError('Неизвестный декоратор метода')
            if n.name.startswith('__'): raise ValueError('Специальный метод требует отдельного связывания')
            methods[n.name]=(n,decorators[0] if decorators else 'method')
        else: raise ValueError('Не перенесён узел класса: '+ast.dump(n))
    guard=prefix.upper()+'_RECORD_H'
    header=['/* Весь скалярный dataclass сгенерирован из AST, без проекции эффектов. */',
            '#ifndef '+guard,'#define '+guard,'#ifndef PY_RECORD_API','#define PY_RECORD_API','#endif',
            '#include <stdint.h>','#ifndef PY_RECORD_MAYBE_I32','#define PY_RECORD_MAYBE_I32',
            'typedef struct { int32_t value; uint8_t present; } PyRecordMaybeI32;','#endif',
            'typedef struct {',*[f'    {t} {name};' for name,t in fields.items()],'} '+prefix+';']
    emitter=RecordEmitter(constants,fields,methods,prefix)
    # Чистые свойства можно подставлять в C-выражения; эффектные вызовы требуют
    # отдельной инструкции, иначе C не гарантирует порядок вычисления Python.
    dependencies={name:set() for name in methods}
    pure=set(methods)
    for name,(node,kind) in methods.items():
        for part in ast.walk(node):
            if isinstance(part,(ast.Assign,ast.AnnAssign,ast.AugAssign)):
                targets=part.targets if isinstance(part,ast.Assign) else [part.target]
                if any(not isinstance(target,ast.Name) for target in targets): pure.discard(name)
            if isinstance(part,ast.Call):
                if isinstance(part.func,ast.Attribute) and ast.unparse(part.func.value)=='self':
                    dependencies[name].add(part.func.attr)
                elif not isinstance(part.func,ast.Name) or part.func.id not in ('min','max','int','bool'):
                    pure.discard(name)
            if isinstance(part,ast.Attribute) and ast.unparse(part.value)=='self' and part.attr in methods and methods[part.attr][1]=='property':
                dependencies[name].add(part.attr)
    while True:
        following={name for name in pure if dependencies[name]<=pure}
        if following==pure: break
        pure=following
    depths={}
    def depth(name,active):
        if name in active: raise ValueError('Рекурсивный вызов записи не имеет доказанной границы стека')
        if name not in methods: raise ValueError('Неизвестный метод записи: '+name)
        if name not in depths:
            depths[name]=1+max([0,*[depth(child,active|{name}) for child in dependencies[name]]])
        return depths[name]
    for name in methods: depth(name,set())
    if any(kind=='property' and name not in pure for name,(_,kind) in methods.items()):
        raise ValueError('Свойство с побочными эффектами требует последовательного IR')
    emitter.pure_methods=pure
    boolean_fields={'self.'+n.target.id for n in owner.body if isinstance(n,ast.AnnAssign) and ast.unparse(n.annotation)=='bool'}
    field_optional={'self.'+k:'record->'+k for k,v in fields.items() if v=='PyRecordMaybeI32'}
    emitter.optional=dict(field_optional)
    initial=[]
    for name,value in defaults.items():
        initial.append(ast.copy_location(ast.Assign(targets=[ast.Attribute(value=ast.Name(id='self',ctx=ast.Load()),attr=name,ctx=ast.Store())],value=value),value))
    init_signature='PY_RECORD_API void '+prefix+'_init('+prefix+' *record)'
    header.append(init_signature+';')
    code=[emitter.function(init_signature,initial)]
    inventory=[]
    for name,(node,kind) in methods.items():
        if node.args.vararg or node.args.kwarg or node.args.kwonlyargs or node.args.defaults or node.args.posonlyargs:
            raise ValueError('Неподдержанная сигнатура: '+name)
        arguments=list(node.args.args)
        params=[]; signature=[]
        emitter.optional=dict(field_optional); emitter.nonnull=set()
        emitter.boolean_names=set(boolean_fields)
        if kind!='staticmethod':
            if not arguments or arguments.pop(0).arg!='self': raise ValueError('Нет явного self')
            signature.append(prefix+' *record')
        for arg in arguments:
            ctype=annotation(arg.annotation)
            if ctype=='void': raise ValueError('Аргумент None без int')
            params.append(arg.arg)
            if ast.unparse(arg.annotation)=='bool': emitter.boolean_names.add(arg.arg)
            signature.append(('const PyRecordMaybeI32 *' if ctype=='PyRecordMaybeI32' else ctype+' ')+arg.arg)
            if ctype=='PyRecordMaybeI32': emitter.optional[arg.arg]='(*'+arg.arg+')'
        prototype='PY_RECORD_API '+annotation(node.returns)+' '+prefix+'_'+name+'('+(', '.join(signature) or 'void')+')'
        header.append(prototype+';')
        bound={*params,*(n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store))}
        emitter.constants={key:value for key,value in constants.items() if key not in bound}
        code.append(emitter.function(prototype,node.body,parameters=params))
        inventory.append(dict(name=name,kind=kind,line=node.lineno,end=node.end_lineno,
                              ast_sha256=hashlib.sha256(ast.dump(node).encode()).hexdigest()))
    sets=[]
    for values,index in emitter.sets.items():
        if not values:
            sets.append(f'static uint8_t {prefix}_set_{index}(int32_t value) {{ (void)value; return 0; }}')
            continue
        low,high=values[0],values[-1]
        if high-low>=65536: raise ValueError('Слишком широкий диапазон конечного множества')
        bits=bytearray((high-low+8)//8)
        for value in values: bits[(value-low)>>3]|=1<<((value-low)&7)
        sets += [f'static const uint8_t {prefix}_set_bits_{index}[] = {{'+','.join(map(str,bits))+'};',
                 f'static uint8_t {prefix}_set_{index}(int32_t value) {{',
                 '    uint16_t offset;',f'    if(value<{low}L || value>{high}L) return 0;',
                 f'    offset=(uint16_t)(value-{low}L); /* SUB, затем доказанное сужение до u16. */',
                 f'    return ({prefix}_set_bits_{index}[offset>>3]>>(offset&7))&1;', '}']
    header.append('#endif')
    return RecordArtifact('\n'.join(header)+'\n','\n'.join([*sets,*code]),dict(
        class_name=class_name,prefix=prefix,fields=fields,methods=inventory,
        constants_sha256=hashlib.sha256(repr(sorted((k,tuple(sorted(v)) if isinstance(v,frozenset) else v) for k,v in constants.items())).encode()).hexdigest(),
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        complete_declared_bodies=True,excluded_nodes=[],integer_domain='i32, включая промежуточные результаты; optional имеет отдельную метку',
        call_depths=depths,recursive_calls=False,
        pending=['аргументы конструктора dataclass','неявные методы dataclass: eq/repr и прочие',
                 'общий вывод диапазонов i32','циклы без доказанной границы','наследование и объектные контейнеры']))
