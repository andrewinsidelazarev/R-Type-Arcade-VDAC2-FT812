from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from pyz80_compiler.whole_program_vm_stack_bound import _locate_sdcc

ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "Source/C/python_vm"
TCC = next((path for path in (
    Path("E:/zx/tcc-0.9.27/tcc/tcc.exe"),
    ROOT.parent / "tcc-0.9.27/tcc/tcc.exe",
) if path.is_file()), None)
SDCC = _locate_sdcc(ROOT)


CHECK = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "pyz80_target_object_runtime.h"

static PyZ80VMValue symbol(uint16_t id) {
    PyZ80VMValue v = {PYZ80_VM_VALUE_SYMBOL, 0, id, 0}; return v;
}
static PyZ80VMValue integer(int32_t n) {
    PyZ80VMValue v = {PYZ80_VM_VALUE_I32, 0, PYZ80_VM_NO_SYMBOL,
                      (uint32_t)n}; return v;
}

int main(void) {
    PyZ80TargetNode nodes[8];
    PyZ80TargetField fields[8];
    PyZ80VMValue items[16], args[3], object, result;
    const PyZ80TargetAdapterSpec adapters[] = {
        {PYZ80_TARGET_ALLOCATE_INSTANCE, 1, 0},
        {PYZ80_TARGET_STORE_ATTRIBUTE, 3, 0},
        {PYZ80_TARGET_LOAD_ATTRIBUTE, 2, 0},
        {PYZ80_TARGET_BUILD_LIST, 2, 0},
        {PYZ80_TARGET_GET_ITERATOR, 1, 0},
        {PYZ80_TARGET_ITER_NEXT, 1, 0},
        {PYZ80_TARGET_ITER_HAS_VALUE, 1, 0},
        {PYZ80_TARGET_ITER_VALUE, 1, 0},
        {PYZ80_TARGET_BINARY, 3, 0},
        {PYZ80_TARGET_STORE_DATACLASS_FIELDS, 3, 0}
    };
    const PyZ80TargetOperatorSpec operators[] = {
        {12, PYZ80_TARGET_OP_ADD, 0}
    };
    PyZ80TargetContext context;
    const uint16_t keys[2] = {5, 6};
    const uint16_t duplicate_keys[2] = {5, 5};
    PyZ80TargetField before[8];
    PyZ80Target_Init(&context, nodes, 8, fields, 8, items, 16,
                     adapters, 10, operators, 1, 0, 0);
    args[0] = symbol(77);
    if (!PyZ80Target_Invoke(&context, 0, 0, 0, args, 1, 0, &object)) return 1;
    args[0] = object; args[1] = symbol(5); args[2] = integer(1234);
    if (!PyZ80Target_Invoke(&context, 0, 1, 0, args, 3, 0, &result)) return 2;
    args[0] = object; args[1] = symbol(5);
    if (!PyZ80Target_Invoke(&context, 0, 2, 0, args, 2, 0, &result) ||
        result.kind != PYZ80_VM_VALUE_I32 || result.payload != 1234) return 3;
    context.field_keys = keys; context.field_key_count = 2;
    args[0] = object; args[1] = integer(88); args[2] = integer(99);
    context.field_capacity = 1;
    memcpy(before, fields, sizeof(fields));
    if (PyZ80Target_Invoke(&context, 0, 9, 0, args, 3, 0, &result) ||
        memcmp(before, fields, sizeof(fields)) || context.field_used != 1) return 9;
    context.field_capacity = 8;
    if (!PyZ80Target_Invoke(&context, 0, 9, 0, args, 3, 0, &result) ||
        result.kind != PYZ80_VM_VALUE_NONE || context.field_used != 2) return 10;
    if (!PyZ80Target_LoadField(&context, &object, 5, &result) || result.payload != 88) return 11;
    if (!PyZ80Target_LoadField(&context, &object, 6, &result) || result.payload != 99) return 12;
    context.field_keys = duplicate_keys;
    memcpy(before, fields, sizeof(fields));
    if (PyZ80Target_Invoke(&context, 0, 9, 0, args, 3, 0, &result) ||
        memcmp(before, fields, sizeof(fields))) return 13;
    context.field_keys = keys; context.field_key_count = 1;
    if (PyZ80Target_Invoke(&context, 0, 9, 0, args, 3, 0, &result)) return 14;
    context.field_key_count = 2;
    fields[0].next = 1;
    if (PyZ80Target_Invoke(&context, 0, 9, 0, args, 3, 0, &result)) return 15;
    if (PyZ80Target_LoadField(&context, &object, 999, &result)) return 16;
    if (PyZ80Target_StoreField(&context, &object, 999, &result)) return 17;
    if (memcmp(before, fields, sizeof(fields)) == 0) return 18;
    /* The only difference must be our deliberately corrupt link. */
    fields[0].next = 0;
    if (memcmp(before, fields, sizeof(fields))) return 19;
    args[0] = integer(4); args[1] = integer(9);
    if (!PyZ80Target_Invoke(&context, 0, 3, 0, args, 2, 0, &result)) return 4;
    args[0] = result;
    if (!PyZ80Target_Invoke(&context, 0, 4, 0, args, 1, 0, &object)) return 5;
    args[0] = object;
    if (!PyZ80Target_Invoke(&context, 0, 5, 0, args, 1, 0, &result)) return 6;
    args[0] = result;
    if (!PyZ80Target_Invoke(&context, 0, 7, 0, args, 1, 0, &result) ||
        result.payload != 4) return 7;
    args[0] = symbol(12); args[1] = integer(20); args[2] = integer(22);
    if (!PyZ80Target_Invoke(&context, 0, 8, 0, args, 3, 0, &result) ||
        result.payload != 42) return 8;
    puts("PZTARGET_OBJECT_OK");
    return 0;
}
'''


class TargetObjectRuntimeTests(unittest.TestCase):
    @unittest.skipUnless(SDCC is not None, "pinned SDCC unavailable")
    def test_object_runtime_compiles_for_z80_without_static_scratch_data(self):
        with tempfile.TemporaryDirectory(prefix="pyz80-target-z80-") as raw:
            directory = Path(raw)
            for name in ("pyz80_target_object_runtime.c", "pyz80_target_object_runtime.h",
                         "pyz80_whole_program_vm.h", "pyz80_target_deque.h", "pyz80_target_buffers.h"):
                shutil.copy2(RUNTIME / name, directory / name)
            environment = os.environ.copy()
            environment["PATH"] = str(SDCC.parent) + os.pathsep + environment.get("PATH", "")
            compiled = subprocess.run(
                [str(SDCC), "-mz80", "--std-c11", "--sdcccall", "1",
                 "--fno-omit-frame-pointer", "--stack-auto", "--opt-code-speed",
                 "--no-c-code-in-asm", "-c", "pyz80_target_object_runtime.c"],
                cwd=directory, env=environment, capture_output=True, text=True,
                # Время офлайн-оптимизации SDCC, не допустимое время игрового кадра.
                timeout=600)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            relocatable = (directory / "pyz80_target_object_runtime.rel").read_text(
                encoding="latin1")
            self.assertIn("A _CODE size ", relocatable)
            self.assertIn("A _DATA size 0 ", relocatable)

    @unittest.skipUnless(TCC is not None, "TCC host compiler unavailable")
    def test_persistent_fields_collections_iterators_and_arithmetic(self) -> None:
        assert TCC is not None
        with tempfile.TemporaryDirectory(prefix="pyz80-target-object-") as raw:
            directory = Path(raw)
            for name in (
                    "pyz80_target_object_runtime.c", "pyz80_target_deque.c", "pyz80_target_deque.h", "pyz80_target_buffers.c", "pyz80_target_buffers.h",
                    "pyz80_target_object_runtime.h",
                    "pyz80_whole_program_vm.c",
                    "pyz80_whole_program_vm.h"):
                shutil.copy2(RUNTIME / name, directory / name)
            (directory / "check.c").write_text(CHECK, encoding="utf-8")
            compiled = subprocess.run(
                [str(TCC), "-std=c11", "-Wall", "-Werror", "-o",
                 "check.exe", "check.c", "pyz80_target_object_runtime.c", "pyz80_whole_program_vm.c", "pyz80_target_deque.c", "pyz80_target_buffers.c"],
                cwd=directory, check=False, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout)
            executed = subprocess.run(
                [str(directory / "check.exe")], cwd=directory, check=False,
                text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                encoding="utf-8", errors="replace", timeout=120)
            self.assertEqual(executed.returncode, 0, executed.stdout)
            self.assertIn("PZTARGET_OBJECT_OK", executed.stdout)


if __name__ == "__main__":
    unittest.main()
