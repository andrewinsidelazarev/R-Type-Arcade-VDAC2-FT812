"""Полные тела типизированных функций и методы с явно связанными байтовыми полями.

struct разбирается на ПК, в целевом коде остаются проверки диапазонов и доступ
к байтам через непрерывное окно либо логический адрес и банковый провайдер.
Это статический backend, не обещание готового struct в объектной VM.
Исключение останавливает вызов через ABI ошибки; перехват пока не поддержан.
"""
import ast
import hashlib
from dataclasses import dataclass

from .demo_projection import ScalarRecordEmitter
from .record_backend import constant
from .struct_provider import format_plan
from .definite_scalars import check_definite_scalars


@dataclass
class BufferArtifact:
    header: str
    code: str
    manifest: dict


class BufferEmitter(ScalarRecordEmitter):
    def __init__(self,constants,buffers,prefix,load_counts,optimise,*,views=False,bindings=None,arrays=None):
        super().__init__(constants,bindings)
        self.buffers=buffers; self.prefix=prefix; self.formats={}; self.loop_bounds=[]
        self.load_counts=load_counts;self.optimise=optimise;self.copy_runs=[]
        self.views=views;self.arrays=arrays or {};self.selected_buffers=[]

    def copy_run(self,node,count):
        """Доказать обратимость struct и непрерывность конечного цикла копии."""
        if self.views or not self.optimise or not count or len(node.body)!=3: return None
        unpack,pack,step=node.body
        if (not isinstance(unpack,ast.Assign) or len(unpack.targets)!=1 or
            not isinstance(unpack.targets[0],(ast.Tuple,ast.List)) or
            not isinstance(unpack.value,ast.Call) or ast.unparse(unpack.value.func)!='struct.unpack_from' or
            not isinstance(pack,ast.Expr) or not isinstance(pack.value,ast.Call) or
            ast.unparse(pack.value.func)!='struct.pack_into' or
            not isinstance(step,ast.AugAssign) or not isinstance(step.target,ast.Name) or
            not isinstance(step.op,ast.Add)):
            return None
        read=unpack.value;write=pack.value
        if read.keywords or write.keywords or len(read.args)!=3 or len(write.args)<3: return None
        targets=unpack.targets[0].elts
        if any(not isinstance(t,ast.Name) or self.load_counts.get(t.id)!=1 for t in targets): return None
        if [ast.unparse(t) for t in targets]!=[ast.unparse(t) for t in write.args[3:]]: return None
        if ast.unparse(read.args[0])!=ast.unparse(write.args[0]): return None
        _,plan=self.plan(read.args[0]);size=plan['bytes']
        if not size or any((code&127)==0 for _,code in plan['runs']): return None
        if constant(step.value,self.constants)!=size or ast.unparse(read.args[2])!=step.target.id: return None
        if step.target.id==node.target.id: return None
        offset=write.args[2]
        if not isinstance(offset,ast.BinOp) or not isinstance(offset.op,ast.Add): return None
        product=offset.right
        if (not isinstance(product,ast.BinOp) or not isinstance(product.op,ast.Mult) or
            ast.unparse(product.left)!=node.target.id or constant(product.right,self.constants)!=size): return None
        if any(isinstance(n,ast.Name) and n.id in (node.target.id,step.target.id) for n in ast.walk(offset.left)): return None
        source=self.buffer(read.args[1]);target=self.buffer(write.args[1],writable=True)
        # Размеры и отсутствие перекрытия проверяются в runtime. Если быстрый
        # путь невозможен, исходное тело сохраняет частичные записи и ошибку.
        return source,self.expr(read.args[2]),target,self.expr(offset.left),size*count,step.target.id

    def buffer(self,node,writable=False):
        key=ast.unparse(node)
        if key not in self.buffers:
            raise ValueError('Не связан байтовый буфер: '+ast.unparse(node))
        if writable and self.buffers[key]!='bytearray':
            raise ValueError('Запись в неизменяемый bytes')
        return self.aliases.get(key,key)

    def select_buffer(self,node,writable,indent):
        if isinstance(node,ast.Subscript) and ast.unparse(node.value) in self.arrays:
            key=ast.unparse(node.value)
            if writable and self.arrays[key]!='bytearray': raise ValueError('Запись в неизменяемый bytes')
            name='pybuf_selected_'+str(len(self.selected_buffers))
            self.selected_buffers.append(name)
            index=self.expr(node.slice)
            return name,[f'{indent}pybuf_error=PyView_Index({self.aliases[key]},{index},&{name});',
                         f'{indent}if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,{node.lineno});']
        return self.buffer(node,writable),[]

    def plan(self,node):
        value=constant(node,self.constants)
        plan=format_plan(value)
        if plan is None or plan['bytes']>64 or plan['values']>16:
            raise ValueError('Не поддержан конечный struct-формат: '+repr(value))
        if any((code&127)==5 for repeat,code in plan['runs']):
            raise ValueError('Unsigned32 требует числового типа шире i32')
        index=self.formats.setdefault(value,(len(self.formats),plan))[0]
        return index,plan

    def expr(self,node):
        if isinstance(node,ast.Name):
            if node.id in self.buffers: raise ValueError('Буфер не является скаляром')
            if node.id.startswith('pybuf_'): raise ValueError('Имя зарезервировано ABI')
        if isinstance(node,(ast.Attribute,ast.Subscript,ast.BoolOp)):
            raise ValueError('Не связана семантика выражения: '+ast.unparse(node))
        if isinstance(node,ast.Compare) and any(isinstance(op,(ast.Is,ast.IsNot)) for op in node.ops):
            raise ValueError('Идентичность не заменяется равенством')
        if isinstance(node,ast.Constant) and node.value is None:
            raise ValueError('None не является нулём')
        if isinstance(node,ast.Call):
            name=ast.unparse(node.func)
            if node.keywords: raise ValueError('Именованные вызовы пока не связаны')
            if name=='len' and len(node.args)==1:
                return '((int32_t)'+self.buffer(node.args[0])+'->size)'
            if name=='struct.calcsize' and len(node.args)==1:
                return str(self.plan(node.args[0])[1]['bytes'])+'L'
            if name in ('int','bool'):
                if len(node.args)!=1: raise ValueError('Нужен один скалярный аргумент')
                value=self.expr(node.args[0])
                return f'(({value}) != 0)' if name=='bool' else f'((int32_t)({value}))'
            if name in ('min','max'):
                if len(node.args)!=2: raise ValueError('Нужны два скалярных аргумента')
                return 'PyBuf_'+name.title()+'('+','.join(self.expr(arg) for arg in node.args)+')'
            if name not in ('min','max','int','bool'):
                raise ValueError('Неизвестный или эффектный вызов: '+name)
        return super().expr(node)

    def statements(self,nodes,indent='    '):
        lines=[]
        for node in nodes:
            marker=f'{indent}/* Python: строка {node.lineno}. */'
            if isinstance(node,ast.Raise):
                if (node.cause is not None or not isinstance(node.exc,ast.Call) or
                    ast.unparse(node.exc.func)!='ValueError' or node.exc.keywords or
                    len(node.exc.args)!=1 or not isinstance(node.exc.args[0],ast.Constant) or
                    not isinstance(node.exc.args[0].value,str)):
                    raise ValueError('Не связано исключение')
                lines += [marker,f'{indent}return PyBuf_Fail(pybuf_fault,PYBUF_SOURCE_VALUE,{node.lineno});']
                continue
            if isinstance(node,ast.Return):
                if node.value is not None and not (isinstance(node.value,ast.Constant) and node.value.value is None):
                    raise ValueError('Буферный ABI пока возвращает только None/ошибку')
                lines += [marker,indent+'return 1;']; continue
            if isinstance(node,ast.While): raise ValueError('Нет доказанной границы while')
            if isinstance(node,ast.For):
                if (node.orelse or not isinstance(node.target,ast.Name) or
                    not isinstance(node.iter,ast.Call) or ast.unparse(node.iter.func)!='range' or
                    node.iter.keywords or len(node.iter.args)!=1):
                    raise ValueError('Не поддержан диапазон цикла')
                count=constant(node.iter.args[0],self.constants)
                if type(count) is not int or not 0<=count<=256: raise ValueError('Не доказана граница range')
                self.loop_bounds.append(dict(line=node.lineno,iterations=count))
                # Не менять range в AST: проверка полного тела хранит исходный хеш.
                self.locals.add(node.target.id)
                name=self.expr(node.target)
                iterator='pybuf_loop_'+str(len(self.loop_bounds))
                self.locals.add(iterator)
                # В Python присваивание переменной цикла не меняет range;
                # после цикла она сохраняет последнее значение, не stop.
                run=self.copy_run(node,count)
                loop_indent=indent+'    ' if run else indent
                body=[marker,f'{loop_indent}for({iterator}=0; {iterator}<{count}; ++{iterator}) {{',
                      f'{loop_indent}    {name}={iterator};',
                      *self.statements(node.body,loop_indent+'    '),loop_indent+'}']
                if run:
                    source,read,target,write,size,cursor=run
                    self.copy_runs.append(dict(line=node.lineno,bytes=size,iterations=count,
                                              proof='identical non-padding integer format; dead unpack temporaries; linear disjoint spans'))
                    lines += [f'{indent}/* Доказанный непрерывный цикл; иначе исходный путь. */',
                              f'{indent}if(PyBuf_TryCopyRun({source},{read},{target},{write},{size})) {{',
                              f'{indent}    {cursor}+={size}L; {name}={count-1}L;',
                              indent+'} else {',*body,indent+'}']
                else: lines+=body
                continue
            call=None; targets=None; result_indices=None
            if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.value,ast.Call):
                if ast.unparse(node.value.func)=='struct.unpack_from':
                    call=node.value
                    if not isinstance(node.targets[0],(ast.Tuple,ast.List)):
                        raise ValueError('unpack_from требует явное распаковывание результата')
                    targets=node.targets[0].elts
            if (isinstance(node,ast.Assign) and len(node.targets)==1 and
                isinstance(node.value,ast.Subscript) and isinstance(node.value.value,ast.Call) and
                ast.unparse(node.value.value.func)=='struct.unpack_from'):
                call=node.value.value
                index=constant(node.value.slice,self.constants)
                if type(index) is not int: raise ValueError('Нужен постоянный индекс результата struct')
                targets=[node.targets[0]];result_indices=[index]
            if isinstance(node,ast.Expr) and isinstance(node.value,ast.Call) and ast.unparse(node.value.func)=='struct.pack_into':
                call=node.value
            if call is not None:
                if call.keywords or len(call.args)<2: raise ValueError('Не связана сигнатура struct')
                unpack=targets is not None
                index,plan=self.plan(call.args[0])
                buffer,selection=self.select_buffer(call.args[1],not unpack,indent)
                if unpack:
                    if result_indices is not None:
                        result_indices=[i+plan['values'] if i<0 else i for i in result_indices]
                        if any(not 0<=i<plan['values'] for i in result_indices):
                            raise ValueError('Индекс вне результата struct')
                    elif len(targets)!=plan['values']: raise ValueError('Не совпадает распаковывание struct')
                    if len(call.args) not in (2,3) or any(not isinstance(t,ast.Name) for t in targets):
                        raise ValueError('Не совпадает распаковывание struct')
                elif len(call.args)!=3+plan['values']:
                    raise ValueError('Не совпадает число pack_into аргументов')
                offset=self.expr(call.args[2]) if len(call.args)>2 else '0L'
                lines.append(marker)
                lines.extend(selection)
                if not unpack:
                    lines += [f'{indent}pybuf_values[{i}]={self.expr(v)};' for i,v in enumerate(call.args[3:])]
                name=self.prefix+('_unpack_' if unpack else '_pack_')+str(index)
                lines += [f'{indent}pybuf_error={name}({buffer},{offset},pybuf_values);',
                          f'{indent}if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,{node.lineno});']
                if unpack:
                    for i,target in zip(result_indices if result_indices is not None else range(len(targets)),targets):
                        if target.id in self.buffers: raise ValueError('Буфер нельзя заменить скаляром')
                        self.locals.add(target.id)
                        lines.append(f'{indent}{self.expr(target)}=pybuf_values[{i}];')
                continue
            if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign)):
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                if any(not isinstance(t,ast.Name) or t.id in self.buffers for t in targets):
                    raise ValueError('Не скалярная локальная запись')
            lines += super().statements([node],indent)
        return lines

    def helpers(self):
        lines=[]
        span_type='PyBufferView' if self.views else 'PyBufferSpan'
        position_type='uint32_t' if self.views else 'uint16_t'
        access='PyView' if self.views else 'PyBuf'
        for index,plan in self.formats.values():
            for unpack in (True,False):
                name=self.prefix+('_unpack_' if unpack else '_pack_')+str(index)
                lines += [f'static uint8_t {name}({span_type} *buffer,int32_t offset,int32_t *values) {{',
                          f'    {position_type} position;', '    uint8_t error;',
                          *([] if unpack else ['    if(!buffer->writable) return PYBUF_READONLY;']),
                          f'    error={access}_Range(buffer,offset,{plan["bytes"]},&position);',
                          '    if(error) return error;']
                byte=0;value=0
                for repeat,encoded in plan['runs']:
                    code=encoded&127;big=int(bool(encoded&128))
                    width=1 if code<=2 else 2 if code<=4 else 4
                    sign=int(code in (2,4,6))
                    for _ in range(repeat):
                        if code==0:
                            if not unpack:
                                if self.views:
                                    lines += [f'    error=PyView_Write(buffer,position+{byte},1,0,0,0);',
                                              '    if(error) return error;']
                                else: lines.append(f'    buffer->data[position+{byte}]=0;')
                        elif unpack:
                            if self.views:
                                lines += [f'    error=PyView_Read(buffer,position+{byte},{width},{big},{sign},&values[{value}]);',
                                          '    if(error) return error;']
                            else: lines.append(f'    values[{value}]=PyBuf_Read(buffer,position+{byte},{width},{big},{sign});')
                            value+=1
                        else:
                            lines += [f'    error={access}_Write(buffer,position+{byte},{width},{big},{sign},values[{value}]);',
                                      '    if(error) return error;']
                            value+=1
                        byte+=width
                lines += ['    return 0;','}']
        return '\n'.join(lines)+'\n'

def compile_buffer_function(source,function_name,prefix=None,*,optimise=True,memory='span',owner=None,fields=None):
    tree=ast.parse(source);prefix=prefix or function_name
    if memory not in ('span','view'): raise ValueError('Неизвестный провайдер памяти')
    if owner is not None:
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==owner)
        function=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name==function_name)
        if not function.args.args or function.args.args[0].arg!='self': raise ValueError('Нужен обычный метод self')
        if any(isinstance(n,ast.Name) and n.id=='self' and isinstance(n.ctx,ast.Store) for n in ast.walk(function)):
            raise ValueError('Переприсваивание self требует объектного ABI')
    else:
        if fields: raise ValueError('Поля допустимы только для метода')
        function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name==function_name)
    if (function.decorator_list or function.args.defaults or function.args.kwonlyargs or
        function.args.posonlyargs or function.args.vararg or function.args.kwarg or
        function.returns is None or ast.unparse(function.returns)!='None'):
        raise ValueError('Нужна типизированная функция с возвратом None')
    constants={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name):
            try: constants[node.targets[0].id]=constant(node.value,constants)
            except (ValueError,TypeError,ArithmeticError): pass
    buffers={};arrays={};bindings={};parameters=[];signature=['PyBufferFault *pybuf_fault']
    view_type='PyBufferView' if memory=='view' else 'PyBufferSpan'
    for index,(name,kind) in enumerate((fields or {}).items()):
        if not name.startswith('self.') or len(name.split('.'))!=2: raise ValueError('Нужно прямое поле self')
        parameter='pybuf_field_'+str(index);bindings[name]=parameter;parameters.append(parameter)
        if kind in ('bytes','bytearray'):
            buffers[name]=kind;signature.append(view_type+' *'+parameter)
        elif memory=='view' and kind in ('list[bytes]','list[bytearray]'):
            arrays[name]=kind[5:-1];signature.append('PyBufferViewArray *'+parameter)
        else: raise ValueError('Не связан тип поля: '+kind)
    for arg in function.args.args[(1 if owner else 0):]:
        kind=ast.unparse(arg.annotation) if arg.annotation is not None else None
        if kind not in ('int','bool','bytes','bytearray') or arg.arg.startswith('pybuf_'):
            raise ValueError('Не связан тип параметра: '+str(kind))
        if kind in ('bytes','bytearray'): buffers[arg.arg]=kind
        signature.append((view_type+' *' if arg.arg in buffers else 'int32_t ')+arg.arg)
        parameters.append(arg.arg)
    loads={}
    for node in ast.walk(function):
        if isinstance(node,ast.Name) and isinstance(node.ctx,ast.Load): loads[node.id]=loads.get(node.id,0)+1
    bound={*parameters,*(n.id for n in ast.walk(function) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store))}
    constants={name:value for name,value in constants.items() if name not in bound}
    check_definite_scalars(function.body,[*parameters,*(['self'] if owner else [])],constants)
    emitter=BufferEmitter(constants,buffers,prefix,loads,optimise,views=memory=='view',bindings=bindings,arrays=arrays)
    prototype='PY_BUFFER_API uint8_t '+prefix+'('+','.join(signature)+')'
    body=emitter.function(prototype,function.body,parameters=parameters,
         prefix=('    uint8_t pybuf_error;','    int32_t pybuf_values[16];',
                 '    pybuf_fault->error=0; pybuf_fault->line=0;'))
    body=body.rsplit('}',1)[0]+'    return 1;\n}\n'
    if emitter.selected_buffers:
        body=body.replace('    uint8_t pybuf_error;',
            '\n'.join('    PyBufferView *'+name+';' for name in emitter.selected_buffers)+'\n    uint8_t pybuf_error;')
    temporary=max([1,*[plan['values'] for _,plan in emitter.formats.values()]])
    body=body.replace('pybuf_values[16]',f'pybuf_values[{temporary}]')
    header='#include "pyz80_buffer_'+('view' if memory=='view' else 'span')+'.h"\n#ifndef PY_BUFFER_API\n#define PY_BUFFER_API\n#endif\n'+prototype+';\n'
    return BufferArtifact(header,emitter.helpers()+body,dict(function=function_name,owner=owner,prefix=prefix,
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        ast_sha256=hashlib.sha256(ast.dump(function).encode()).hexdigest(),
        source_lines=[function.lineno,function.end_lineno],complete_body=True,excluded_nodes=[],
        buffers=buffers,buffer_arrays=arrays,field_bindings=bindings,formats=list(emitter.formats),loop_bounds=emitter.loop_bounds,copy_runs=emitter.copy_runs,
        buffer_contract=('logical view, length <=2147483647; callback transfers bytes and restores mapping' if memory=='view' else
                         'CPU-mapped contiguous span, length <=65535; backing memory stays mapped during call'),
        integer_domain='i32, including intermediate arithmetic',
        exception_abi='first error aborts call with code and source line; not catchable yet',
        pending=['buffer allocation/resizing and ownership','catchable exceptions','general i32 range inference',
                 'VM struct dispatch','unsigned32 results','dynamic formats','unbounded loops'] ))
