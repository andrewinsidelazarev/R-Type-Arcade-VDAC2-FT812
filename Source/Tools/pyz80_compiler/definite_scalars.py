"""Не допускать чтения неинициализированных локальных переменных в C."""
import ast


def check_definite_scalars(nodes,parameters,constants,*,allow_continue=False):
    def expression(node,bound):
        if node is None: return
        if isinstance(node,ast.Name):
            if isinstance(node.ctx,ast.Load) and node.id not in bound and node.id not in constants:
                raise ValueError('Нет доказанного присваивания: '+node.id)
            return
        if isinstance(node,ast.Call):
            # Связывание имени вызываемой функции проверяет сам backend.
            if isinstance(node.func,ast.Attribute) and not (isinstance(node.func.value,ast.Name) and node.func.value.id=='struct'):
                expression(node.func.value,bound)
            for arg in node.args: expression(arg,bound)
            for arg in node.keywords: expression(arg.value,bound)
            return
        for child in ast.iter_child_nodes(node): expression(child,bound)

    def assigned(target,bound):
        if isinstance(target,ast.Name): return bound|{target.id}
        if isinstance(target,(ast.Tuple,ast.List)):
            for item in target.elts: bound=assigned(item,bound)
            return bound
        expression(target,bound)
        return bound

    def block(body,bound):
        bound=set(bound)
        for node in body:
            if isinstance(node,(ast.Assign,ast.AnnAssign,ast.AugAssign)):
                if isinstance(node,ast.AugAssign) and isinstance(node.target,ast.Name) and node.target.id not in bound:
                    raise ValueError('Нет доказанного присваивания: '+node.target.id)
                expression(node.value,bound)
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                for target in targets: bound=assigned(target,bound)
            elif isinstance(node,ast.If):
                expression(node.test,bound)
                bound=block(node.body,bound)&block(node.orelse,bound)
            elif isinstance(node,ast.For):
                expression(node.iter,bound)
                block(node.body,assigned(node.target,bound))
                # Внешние присваивания тела пока не доказываются. Сам range с
                # известным положительным count гарантирует значение индекса.
                if (isinstance(node.iter,ast.Call) and ast.unparse(node.iter.func)=='range' and
                    len(node.iter.args)==1 and isinstance(node.iter.args[0],ast.Constant) and
                    type(node.iter.args[0].value) is int and node.iter.args[0].value>0):
                    bound=assigned(node.target,bound)
            elif isinstance(node,(ast.Continue,ast.Break)):
                # Состояние после тела цикла наружу не переносится. Разрешить
                # continue без усиления доказанных присваиваний безопасно;
                # корректность положения перехода проверяет вызывающий backend.
                if allow_continue and isinstance(node,ast.Continue): continue
                raise ValueError('Переход цикла требует анализа присваиваний по рёбрам CFG')
            elif isinstance(node,ast.Raise):
                if isinstance(node.exc,ast.Call):
                    for arg in node.exc.args: expression(arg,bound)
            elif isinstance(node,ast.Expr): expression(node.value,bound)
            elif isinstance(node,ast.Return): expression(node.value,bound)
            else:
                # Неизвестная инструкция отдельно отвергается генератором.
                for child in ast.iter_child_nodes(node): expression(child,bound)
        return bound
    block(nodes,set(parameters))
