"""Статические агрегаты: целочисленные массивы, байтовые поля и вызовы методов.

Размеры/владение заданы схемой, тела методов берутся целиком. Эффектные вызовы
разрешены отдельными инструкциями с распространением ошибки. Провайдеры
отдельно связывают ресурсный конструктор и специализированные байтовые методы.
"""
import ast
import hashlib
from dataclasses import dataclass

from .buffer_backend import BufferEmitter
from .record_backend import constant
from .definite_scalars import check_definite_scalars


@dataclass
class AggregateArtifact:
    header: str
    code: str
    manifest: dict


class AggregateEmitter(BufferEmitter):
    def __init__(self,constants,fields,methods,prefix,records,method_name):
        bindings={'self':'record'}
        buffers={};arrays={}
        for name,kind in fields.items():
            if kind=='bytes':
                buffers['self.'+name]='bytes';bindings['self.'+name]='(&record->'+name+')'
            elif kind=='list[bytearray]':
                arrays['self.'+name]='bytearray';bindings['self.'+name]='(&record->'+name+')'
        super().__init__(constants,buffers,prefix+'_'+method_name,{},False,views=True,bindings=bindings,arrays=arrays)
        self.owner_prefix=prefix
        self.fields=fields;self.methods=methods;self.records=records
        self.integer_arrays={};self.pending=[];self.serial=0;self.loop_depth=0
        self.local_arrays={};self.arguments={};self.sets={};self.return_count=0

    def temporary(self):
        self.serial+=1
        name='pyagg_tmp_'+str(self.serial);self.locals.add(name)
        return name

    def array(self,node):
        name=ast.unparse(node)
        if name in self.integer_arrays: return self.integer_arrays[name]
        raise ValueError('Не связан целочисленный массив: '+name)

    def indexed(self,node):
        name,size=self.array(node.value)
        value=self.expr(node.slice)
        index=self.temporary()
        self.pending += [f'{index}={value};',f'if({index}<0) {index}+={size}L;',
                         f'if({index}<0 || {index}>={size}L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,{node.lineno});']
        return f'{name}[(uint16_t){index}]'

    def expr(self,node):
        if isinstance(node,ast.Subscript): return self.indexed(node)
        if isinstance(node,ast.Name) and node.id in self.local_arrays:
            raise ValueError('Массив не является скаляром')
        if isinstance(node,ast.Attribute):
            if isinstance(node.value,ast.Name) and node.value.id in self.arguments:
                record_type=self.records[self.arguments[node.value.id]]
                if node.attr not in record_type['fields']:
                    raise ValueError('Не связано поле внешней записи: '+ast.unparse(node))
                return node.value.id+'->'+node.attr
            raise ValueError('Поле агрегата не является скаляром: '+ast.unparse(node))
        if isinstance(node,ast.Compare) and len(node.ops)==1 and isinstance(node.ops[0],(ast.In,ast.NotIn)):
            members=constant(node.comparators[0],self.constants)
            if not isinstance(members,frozenset) or len(members)>256 or any(type(x) is not int or not -2**31<=x<2**31 for x in members):
                raise ValueError('Membership требует конечного множества i32')
            key=tuple(sorted(members));index=self.sets.setdefault(key,len(self.sets))
            result=f'{self.prefix}_set_{index}({self.expr(node.left)})'
            return '!'+result if isinstance(node.ops[0],ast.NotIn) else result
        if isinstance(node,ast.IfExp) and any(isinstance(n,ast.Subscript) for n in ast.walk(node)):
            raise ValueError('Условный доступ к массиву требует отдельного последовательного IR')
        return super().expr(node)

    def flush(self,indent):
        result=[indent+line for line in self.pending];self.pending=[]
        return result

    def statements(self,nodes,indent='    '):
        lines=[]
        for node in nodes:
            lines.append(f'{indent}/* Python: строка {node.lineno}; {type(node).__name__}. */')
            if isinstance(node,ast.If):
                test=self.expr(node.test)
                lines += [*self.flush(indent),f'{indent}if({test}) {{',*self.statements(node.body,indent+'    ')]
                if node.orelse: lines += [indent+'} else {',*self.statements(node.orelse,indent+'    ')]
                lines.append(indent+'}')
            elif isinstance(node,ast.For):
                if (node.orelse or not isinstance(node.target,ast.Name) or not isinstance(node.iter,ast.Call) or
                    ast.unparse(node.iter.func)!='range' or len(node.iter.args)!=1 or node.iter.keywords):
                    raise ValueError('Нужен конечный range с одним аргументом')
                count=constant(node.iter.args[0],self.constants)
                if type(count) is not int or not 0<=count<=65535: raise ValueError('Нет конечной границы цикла')
                iterator=self.temporary();name=node.target.id
                if name in self.local_arrays: raise ValueError('Индекс цикла не может заменить массив')
                self.locals.add(name);self.loop_depth+=1
                body=self.statements(node.body,indent+'    ');self.loop_depth-=1
                lines += [f'{indent}for({iterator}=0;{iterator}<{count}L;++{iterator}) {{',
                          f'{indent}    {name}={iterator};',*body,indent+'}']
                self.loop_bounds.append(dict(line=node.lineno,iterations=count))
            elif isinstance(node,ast.Continue):
                if not self.loop_depth: raise ValueError('continue вне цикла')
                lines.append(indent+'continue;')
            elif isinstance(node,ast.Assign):
                if len(node.targets)!=1: raise ValueError('Множественное присваивание пока не связано')
                target=node.targets[0]
                if isinstance(node.value,(ast.Tuple,ast.List)):
                    if not isinstance(target,ast.Name) or not node.value.elts: raise ValueError('Нужен именованный конечный массив')
                    name=target.id;size=len(node.value.elts)
                    if name in self.locals or name in self.arguments or name in self.local_arrays:
                        raise ValueError('Переприсваивание массива требует модели идентичности')
                    values=[]
                    for value in node.value.elts:
                        temp=self.temporary();value=self.expr(value)
                        lines += [*self.flush(indent),f'{indent}{temp}={value};'];values.append(temp)
                    self.local_arrays[name]=size;self.integer_arrays[name]=(name,size)
                    lines += [f'{indent}{name}[{i}]={value};' for i,value in enumerate(values)]
                else:
                    value=self.expr(node.value)
                    temporary=self.temporary()
                    lines += [*self.flush(indent),f'{indent}{temporary}={value};']
                    if isinstance(target,ast.Name):
                        if target.id in self.local_arrays or target.id in self.arguments or target.id=='self':
                            raise ValueError('Нельзя заменить агрегат скаляром')
                        self.locals.add(target.id);destination=target.id
                    elif isinstance(target,ast.Subscript):
                        if ast.unparse(target.value) in self.local_arrays:
                            raise ValueError('Локальный tuple неизменяем')
                        destination=self.indexed(target)
                    else: raise ValueError('Не связан получатель присваивания')
                    lines += [*self.flush(indent),f'{indent}{destination}={temporary}; /* MOV после вычисления RHS. */']
            elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Call):
                call=node.value
                if (not isinstance(call.func,ast.Attribute) or ast.unparse(call.func.value)!='self' or
                    call.func.attr not in self.methods or call.keywords):
                    raise ValueError('Не связан эффектный вызов: '+ast.unparse(call))
                method=self.methods[call.func.attr]
                if method.returns is None or ast.unparse(method.returns)!='None' or len(method.args.args)-1!=len(call.args):
                    raise ValueError('Не совпадает сигнатура эффектного вызова')
                args=[]
                for arg,param in zip(call.args,method.args.args[1:]):
                    if ast.unparse(param.annotation)!='int': raise ValueError('Внутренний вызов пока принимает скаляры')
                    temp=self.temporary();value=self.expr(arg)
                    lines += [*self.flush(indent),f'{indent}{temp}={value};'];args.append(temp)
                invocation=self.owner_prefix+'_'+call.func.attr+'(pybuf_fault,record'+''.join(','+a for a in args)+')'
                lines.append(f'{indent}if(!{invocation}) return 0;')
            elif isinstance(node,ast.Return):
                if node.value is None:
                    if self.return_count: raise ValueError('Нет возвращаемого кортежа')
                    lines.append(indent+'return 1;')
                elif (self.return_count and isinstance(node.value,ast.Call) and ast.unparse(node.value.func)=='struct.unpack_from'):
                    if any(isinstance(n,ast.Subscript) and ast.unparse(n.value) in self.integer_arrays for n in ast.walk(node.value)):
                        raise ValueError('Вложенный индекс struct требует отдельного последовательного IR')
                    names=[ast.Name(id='pyagg_result_'+str(i),ctx=ast.Store()) for i in range(self.return_count)]
                    assignment=ast.copy_location(ast.Assign(targets=[ast.Tuple(elts=names,ctx=ast.Store())],value=node.value),node)
                    lines += BufferEmitter.statements(self,[assignment],indent)
                    lines += [f'{indent}result[{i}]={name.id};' for i,name in enumerate(names)]
                    lines.append(indent+'return 1;')
                else: raise ValueError('Не связан результат метода')
            elif isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str): pass
            else: raise ValueError('Не перенесён узел агрегата: '+ast.dump(node))
        return lines


def compile_aggregate(source,owner,prefix,*,fields,providers,records=None):
    records=records or {};tree=ast.parse(source)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==owner)
    if cls.bases or cls.decorator_list: raise ValueError('Нужен класс без наследования и декораторов')
    methods={}
    for node in cls.body:
        if isinstance(node,ast.FunctionDef): methods[node.name]=node
        elif not (isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)):
            raise ValueError('Не перенесён узел класса')
    if set(providers)-set(methods): raise ValueError('Провайдер неизвестного метода')
    graph={name:{n.func.attr for n in ast.walk(method) if isinstance(n,ast.Call) and
                 isinstance(n.func,ast.Attribute) and ast.unparse(n.func.value)=='self'} for name,method in methods.items()}
    def depth(name,active):
        if name in active: raise ValueError('Рекурсия требует отдельного бюджета стека')
        if name not in methods: raise ValueError('Неизвестный вызываемый метод '+name)
        return 1+max([0,*[depth(child,active|{name}) for child in graph[name]]])
    call_depth=max(depth(name,set()) for name in methods)
    constants={}
    for node in tree.body:
        if isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets=node.targets if isinstance(node,ast.Assign) else [node.target]
            if len(targets)==1 and isinstance(targets[0],ast.Name) and node.value is not None:
                try: constants[targets[0].id]=constant(node.value,constants)
                except (ValueError,TypeError,ArithmeticError): pass
    guard=prefix.upper()+'_AGGREGATE_H'
    header=['#ifndef '+guard,'#define '+guard,'#include "pyz80_buffer_view.h"',
            '#ifndef PY_AGGREGATE_API','#define PY_AGGREGATE_API','#endif']
    header += ['#include "'+info['header']+'"' for info in records.values()]
    header += ['typedef struct {']
    for name,kind in fields.items():
        if isinstance(kind,int) and 1<=kind<=256: declaration=f'int32_t {name}[{kind}];'
        elif kind=='bytes': declaration=f'PyBufferView {name};'
        elif kind=='list[bytearray]': declaration=f'PyBufferViewArray {name};'
        else: raise ValueError('Не связан тип поля: '+name)
        header.append('    '+declaration)
    header += ['} '+prefix+';']
    bodies=[];manifest_methods=[]
    for name,method in methods.items():
        if (method.decorator_list or method.args.defaults or method.args.kwonlyargs or method.args.posonlyargs or
            method.args.vararg or method.args.kwarg or not method.args.args or method.args.args[0].arg!='self'):
            raise ValueError('Не связана сигнатура метода')
        if any(isinstance(n,ast.Name) and (n.id.startswith(('pyagg_','pybuf_')) or n.id in ('record','result')) for n in ast.walk(method)):
            raise ValueError('Зарезервированное имя ABI')
        if any(arg.arg in ('record','result') or arg.arg.startswith(('pyagg_','pybuf_')) for arg in method.args.args):
            raise ValueError('Зарезервированное имя аргумента ABI')
        result=ast.unparse(method.returns) if method.returns else None
        count=0
        if result!='None':
            if isinstance(method.returns,ast.Subscript) and ast.unparse(method.returns.value)=='tuple':
                items=method.returns.slice.elts if isinstance(method.returns.slice,ast.Tuple) else [method.returns.slice]
                if any(ast.unparse(item)!='int' for item in items): raise ValueError('Кортеж требует i32')
                count=len(items)
            else: raise ValueError('Не связан результат '+str(result))
        args=['PyBufferFault *pybuf_fault',prefix+' *record'];parameters=['pybuf_fault','record'];argument_types={}
        for arg in method.args.args[1:]:
            kind=ast.unparse(arg.annotation) if arg.annotation else None
            if kind=='int': args.append('int32_t '+arg.arg)
            elif kind in records:
                args.append('const '+records[kind]['c_type']+' *'+arg.arg);argument_types[arg.arg]=kind
            else: raise ValueError('Не связан тип аргумента '+str(kind))
            parameters.append(arg.arg)
        if count: args.append('int32_t *result');parameters.append('result')
        signature='PY_AGGREGATE_API uint8_t '+prefix+'_'+name+'('+','.join(args)+')'
        header.append(signature+';')
        metadata=dict(name=name,source_lines=[method.lineno,method.end_lineno],
                      ast_sha256=hashlib.sha256(ast.dump(method).encode()).hexdigest(),complete_body=True)
        if name in providers:
            metadata.update(kind='provider',provider=providers[name]);manifest_methods.append(metadata);continue
        emitter=AggregateEmitter(constants,fields,methods,prefix,records,name)
        emitter.arguments=argument_types;emitter.return_count=count
        emitter.integer_arrays={'self.'+field:('record->'+field,size) for field,size in fields.items() if isinstance(size,int)}
        check_definite_scalars(method.body,['self',*[a.arg for a in method.args.args[1:]]],constants,allow_continue=True)
        body=emitter.statements(method.body)
        if count and not isinstance(method.body[-1],ast.Return): raise ValueError('Нет доказанного возврата tuple')
        declaration=[f'    int32_t {local};' for local in sorted(emitter.locals-set(parameters))]
        declaration += [f'    int32_t {local}[{size}];' for local,size in emitter.local_arrays.items()]
        declaration += ['    uint8_t pybuf_error;','    int32_t pybuf_values[16];']
        declaration += ['    PyBufferView *'+selected+';' for selected in emitter.selected_buffers]
        helpers=emitter.helpers()
        for values,index in emitter.sets.items():
            # Конечное множество связывается чистой функцией, без повторения чтения аргумента.
            helpers+=f'static uint8_t {emitter.prefix}_set_{index}(int32_t value) {{\n'
            helpers+='    return '+(' || '.join('value=='+str(v)+'L' for v in values) or '0')+';\n}\n'
        bodies.append(helpers+'\n'.join([signature+' {',*declaration,'    pybuf_fault->error=0; pybuf_fault->line=0;',
                                       *body,'    return 1;','}'])+'\n')
        metadata.update(kind='ast',loop_bounds=emitter.loop_bounds);manifest_methods.append(metadata)
    header.append('#endif')
    return AggregateArtifact('\n'.join(header)+'\n','\n'.join(bodies),dict(owner=owner,prefix=prefix,fields=fields,
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),methods=manifest_methods,excluded_methods=[],
        call_graph={name:sorted(children) for name,children in graph.items()},max_method_depth=call_depth,
        contract='fixed owned arrays; borrowed stable byte views; i32 arithmetic; first error aborts method',
        spg_linked=False))
