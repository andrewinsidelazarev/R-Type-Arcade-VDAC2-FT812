"""Нельзя маскировать неподдержанную семантику записи правдоподобным C."""
import unittest
from pyz80_compiler.record_backend import compile_record


class RecordTests(unittest.TestCase):
    def compile(self,body):
        return compile_record('from dataclasses import dataclass\n@dataclass\nclass Record:\n'
            '    x: int = 0\n    pending: int | None = None\n'+body,'Record')

    def test_none_is_not_zero(self):
        result=self.compile('    def put(self, value: int | None) -> None:\n'
            '        if value is not None:\n            self.x = value\n'
            '        self.pending = value\n')
        self.assertIn('(*value).present',result.code)
        self.assertIn('record->pending=(*value)',result.code)
        self.assertTrue(result.manifest['complete_declared_bodies'])

    def test_nullable_dominance(self):
        for body in ('    def get(self) -> int:\n        return self.pending\n',
                     '    def get(self, clear: bool) -> int:\n'
                     '        if self.pending is not None:\n'
                     '            if clear:\n                self.pending = None\n'
                     '            return self.pending\n        return 0\n'):
            with self.assertRaisesRegex(ValueError,'без доказательства'): self.compile(body)

    def test_do_not_replace_python_or_with_c_bool(self):
        with self.assertRaisesRegex(ValueError,'and/or'):
            self.compile('    def get(self) -> int:\n        return self.x or 7\n')

    def test_no_external_calls_or_side_effect_properties(self):
        for body in ('    def get(self) -> int:\n        return unknown(self.x)\n',
                     '    @property\n    def get(self) -> int:\n        self.x += 1\n        return self.x\n',
                     '    def next(self) -> int:\n        self.x += 1\n        return self.x\n'
                     '    def twice(self) -> int:\n        return self.next() + self.next()\n'):
            with self.assertRaises(ValueError): self.compile(body)

    def test_recursive_call_stack_is_rejected(self):
        for body in ('    def again(self) -> int:\n        return self.again()\n',
                     '    @property\n    def first(self) -> int:\n        return self.second\n'
                     '    @property\n    def second(self) -> int:\n        return self.first\n'):
            with self.assertRaisesRegex(ValueError,'границы стека'): self.compile(body)

    def test_local_shadows_global_constant(self):
        source='from dataclasses import dataclass\namount=99\n@dataclass\nclass R:\n    x:int=0\n'
        source+='    def put(self, amount:int)->None:\n        self.x=amount\n'
        result=compile_record(source,'R')
        self.assertIn('record->x = amount;',result.code)


if __name__=='__main__': unittest.main()
