"""Differential execution of the generated target's integer fast path."""
from __future__ import annotations

import operator
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import unittest

from test_pyz80_target_object_runtime import RUNTIME, TCC

CHECK = r'''
#include <stdint.h>
#include <stdio.h>
#include "pyz80_target_object_runtime.h"
static unsigned calls;
static uint8_t fallback(void *c, struct PyZ80VM *vm, uint16_t a,
    uint16_t d, const PyZ80VMValue *v, uint8_t n, uint32_t off, PyZ80VMValue *r)
{
    (void)c; (void)vm; (void)a; (void)d; (void)v; (void)n; (void)off;
    ++calls; r->kind = PYZ80_VM_VALUE_OPAQUE; r->payload = 1234;
    return 1;
}
int main(void) {
    PyZ80TargetContext context;
    PyZ80VMValue args[3], result;
    PyZ80TargetOperatorSpec ops[21];
    const PyZ80TargetAdapterSpec specs[] = {
        {PYZ80_TARGET_BINARY, 3, 0}, {PYZ80_TARGET_COMPARE, 3, 0},
        {PYZ80_TARGET_UNARY, 2, 0}
    };
    unsigned i, op, lk, rk, mode, ok;
    long left, right;
    for (i = 0; i < 21; ++i) {
        ops[i].symbol = (uint16_t)(i+1); ops[i].operation = (uint8_t)(i+1);
        ops[i].reserved = 0;
    }
    PyZ80Target_Init(&context, 0, 0, 0, 0, 0, 0, specs, 3, ops, 21, 0, 0);
    while (scanf("%u %u %ld %u %ld %u", &op, &lk, &left, &rk, &right, &mode) == 6) {
        args[0].kind = PYZ80_VM_VALUE_SYMBOL; args[0].symbol = (uint16_t)op;
        args[0].reserved = 0; args[0].payload = 0;
        args[1].kind = lk ? PYZ80_VM_VALUE_BOOL : PYZ80_VM_VALUE_I32;
        args[1].payload = (uint32_t)left; args[1].symbol = PYZ80_VM_NO_SYMBOL;
        args[1].reserved = 0;
        args[2].kind = rk ? PYZ80_VM_VALUE_BOOL : PYZ80_VM_VALUE_I32;
        args[2].payload = (uint32_t)right; args[2].symbol = PYZ80_VM_NO_SYMBOL;
        args[2].reserved = 0;
        context.provider = mode ? fallback : 0;
        calls = 0;
        ok = PyZ80Target_Invoke(&context, 0, op >= 18 ? 2 : op >= 12 ? 1 : 0,
            0, args, op >= 18 ? 2 : 3, 0, &result);
        printf("%u %u %ld %u\n", ok, result.kind,
               (long)(int32_t)result.payload, calls);
    }
    return 0;
}
'''

OPS = [operator.add, operator.sub, operator.mul, operator.floordiv,
       operator.truediv, operator.mod, operator.and_, operator.or_,
       operator.xor, operator.lshift, operator.rshift, operator.eq,
       operator.ne, operator.lt, operator.le, operator.gt, operator.ge]


class TargetArithmeticTests(unittest.TestCase):
    @unittest.skipUnless(TCC, "TCC unavailable")
    def test_target_results_match_python_including_bounds_and_fallback(self):
        cases = []
        values = [-2147483648, -2147483647, -65536, -32769, -32768, -33,
                  -7, -1, 0, 1, 2, 7, 31, 32, 33, 32767, 32768, 65536,
                  2147483646, 2147483647, False, True]
        rng = random.Random(812)
        pairs = [(a, b) for a in values for b in values]
        pairs.extend((rng.randint(-2**31, 2**31-1), rng.randint(-2**31, 2**31-1))
                     for _ in range(128))
        for op, function in enumerate(OPS, 1):
            for left, right in pairs:
                # Enormous left shifts exceed i32. Avoid allocating huge Python ints.
                if op == 10 and right > 64:
                    expected = 0 if left == 0 else None
                else:
                    try:
                        expected = function(left, right)
                    except (ValueError, ZeroDivisionError):
                        expected = None
                supported = (isinstance(expected, int) and
                             -2**31 <= expected < 2**31)
                cases.append((op, left, right, supported, expected))
        for op, function in ((18, operator.neg), (19, operator.pos),
                             (20, operator.invert), (21, operator.not_)):
            for left in values:
                expected = function(left)
                cases.append((op, left, 0, -2**31 <= expected < 2**31, expected))
        lines = [f"{op} {int(type(a) is bool)} {int(a)} {int(type(b) is bool)} {int(b)} 0"
                 for op, a, b, _, _ in cases]
        lines.extend(["5 0 6 0 3 1", "1 0 2147483647 0 1 1",
                      "18 0 -2147483648 0 0 1"])
        with tempfile.TemporaryDirectory(prefix="pz-arithmetic-") as raw:
            directory = Path(raw)
            for name in ("pyz80_target_object_runtime.c", "pyz80_target_object_runtime.h",
                         "pyz80_whole_program_vm.h", "pyz80_whole_program_vm.c", "pyz80_target_deque.c", "pyz80_target_deque.h", "pyz80_target_buffers.c", "pyz80_target_buffers.h"):
                shutil.copy2(RUNTIME / name, directory / name)
            (directory / "check.c").write_text(CHECK)
            compiled = subprocess.run([str(TCC), "-std=c11", "-Wall", "-Werror",
                                       "-o", "check.exe", "check.c",
                                       "pyz80_target_object_runtime.c", "pyz80_target_deque.c", "pyz80_target_buffers.c", "pyz80_whole_program_vm.c"],
                                      cwd=directory, capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            run = subprocess.run([str(directory / "check.exe")], cwd=directory,
                                 input="\n".join(lines)+"\n", capture_output=True,
                                 text=True, timeout=60)
            self.assertEqual(run.returncode, 0, run.stderr)
        rows = [tuple(map(int, row.split())) for row in run.stdout.splitlines()]
        self.assertEqual(len(rows), len(lines))
        # Obtain target enum values from accepted scalar and bool operations.
        int_kind = next(row[1] for case, row in zip(cases, rows)
                        if case[:3] == (1, 0, 1))
        bool_kind = next(row[1] for case, row in zip(cases, rows)
                         if case[:3] == (12, 0, 1))
        for case, row in zip(cases, rows):
            op, left, right, supported, expected = case
            with self.subTest(op=op, left=left, right=right):
                self.assertEqual(row[0], int(supported))
                self.assertEqual(row[3], 0)
                if supported:
                    self.assertEqual(row[2], expected)
                    self.assertEqual(row[1], bool_kind if type(expected) is bool else int_kind)
        for row in rows[-3:]:
            self.assertEqual((row[0], row[2], row[3]), (1, 1234, 1))
        print(f"Python/C arithmetic cases: {len(cases)}; provider fallback cases: 3")


if __name__ == "__main__":
    unittest.main()
