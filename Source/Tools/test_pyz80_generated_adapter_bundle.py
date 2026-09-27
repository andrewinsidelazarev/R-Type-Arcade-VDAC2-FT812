"""Compile the emitted adapter C, not a hand-written table equivalent."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from generate_pzvt_target_adapters import generate
from pyz80_translation_checkpoint import write_translation_checkpoint
from test_pyz80_dataclass_runtime import dataclass_artifact
from test_pyz80_target_object_runtime import RUNTIME, SDCC, TCC
from test_pyz80_translation_checkpoint import _fixture
from test_pyz80_scope_runtime import source_artifact
from test_pyz80_gc_runtime import source_header


class GeneratedAdapterBundleTests(unittest.TestCase):
    @unittest.skipUnless(TCC, "host compiler unavailable")
    def test_generated_builtin_binding_executes_source(self):
        source = "def factory(seed):\n    def f(a=seed,*,b=2):\n        return len([a,b])+a+b\n    return f(b=5)\n"
        artifact = source_artifact(source)
        with tempfile.TemporaryDirectory(prefix="pyz80-generated-builtins-") as raw:
            root=Path(raw).resolve()
            _fixture(root)
            build=root/"Build"
            vm_path=build/"rtype_python_whole_program_vm_status.json"
            status=json.loads(vm_path.read_bytes())
            digest=hashlib.sha256(artifact.target_bytecode).hexdigest()
            status.update({"artifact_semantic_sha256":artifact.semantic_sha256,
                "function_id_table":artifact.target_coverage["function_id_table"],
                "target_coverage":dict(artifact.target_coverage),
                "adapter_table":list(artifact.adapter_table),
                "target_bytecode":{"sha256":digest,"bytes":len(artifact.target_bytecode)}})
            vm_path.write_text(json.dumps(status))
            stack_path=build/"rtype_python_whole_program_vm_stack_bound_status.json"
            stack=json.loads(stack_path.read_bytes())
            stack["binding"].update({"artifact_semantic_sha256":artifact.semantic_sha256,"target_bytecode_sha256":digest})
            stack_path.write_text(json.dumps(stack))
            (build/"rtype_python_whole_program_vm.bin").write_bytes(artifact.target_bytecode)
            write_translation_checkpoint(root)
            generate(root,build_directory=build,source_directory=build)
            modules=("pyz80_whole_program_vm","pyz80_target_object_runtime","pyz80_target_scope_runtime","pyz80_target_builtins","pyz80_target_call_binding")
            for module in modules:
                for suffix in (".c",".h"):
                    shutil.copy2(RUNTIME/(module+suffix),build/(module+suffix))
            (build/"check.c").write_text('#include "pyz80_target_adapter_plan_generated.h"\n'
                '#include "pyz80_target_scope_runtime.h"\n#include "pyz80_target_builtins.h"\n#include "pyz80_target_call_binding.h"\n' + source_header(source) + r'''
int main(void) {
    PyZ80TargetContext objects;PyZ80TargetScopes scopes;
    unsigned symbol_index,global_count=0;
    PyZ80TargetNode nodes[4];PyZ80TargetField fields[1];PyZ80VMValue items[8],frames[4],globals[2],arg,result,scratch[4];
    PyZ80VM vm;PyZ80VMLimits limits={4,0,32,4};PyZ80VMAdapter adapter;
    PyZ80VMMemoryImage memory={bytes,sizeof(bytes)};
    PyZ80VMImage image={PyZ80VM_MemoryRead,&memory,sizeof(bytes),proof};
    union {uint32_t align;uint8_t bytes[4096];} arena;
    PyZ80Target_Init(&objects,nodes,4,fields,1,items,8,0,0,0,0,0,0);
    PyZ80Generated_Bind(&objects);PyZ80Target_EnableBuiltins(&objects);
    if(!objects.positional_call_flags) return 1;
    for(symbol_index=0;symbol_index<objects.builtin_symbol_count;++symbol_index) {
        if(!PYZ80_BUILTIN_IS_GLOBAL(objects.builtin_symbols[symbol_index].operation))continue;
        if(objects.builtin_symbols[symbol_index].operation!=PYZ80_BUILTIN_LEN)return 1;
        ++global_count;
    }
    if(global_count!=1)return 1;
    if(!PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,0,&globals[0]))return 2;
    globals[1]=globals[0];
    adapter=PyZ80Target_VMAdapter(&objects);
    if(PyZ80VM_Init(&vm,&image,&adapter,arena.bytes,sizeof(arena.bytes),&limits)!=PYZ80_VM_IDLE)return 3;
    if(!PyZ80Target_AttachScopes(&scopes,&objects,&vm,frames,4,globals,2))return 4;
    if(!PyZ80Target_AttachCallBinding(&scopes,scratch,4))return 7;
    arg.kind=PYZ80_VM_VALUE_I32;arg.reserved=0;arg.symbol=PYZ80_VM_NO_SYMBOL;arg.payload=7;
    if(PyZ80VM_StartArgs(&vm,0,&arg,1)!=PYZ80_VM_RUNNING)return 5;
    if(PyZ80VM_Run(&vm,1000,&result)!=PYZ80_VM_RETURNED || result.payload!=14)return 6;
    return 0;
}
''')
            compiled=subprocess.run([str(TCC),"-std=c11","-Wall","-Werror","-o","check.exe","check.c",
                "pyz80_target_adapter_plan_generated.c",*(m+".c" for m in modules)],cwd=build,
                capture_output=True,text=True,timeout=120)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            self.assertEqual(subprocess.run([str(build/"check.exe")],timeout=30).returncode,0)

    @unittest.skipUnless(TCC and SDCC, "host/Z80 compiler unavailable")
    def test_generated_tables_bind_and_compile_on_host_and_z80(self):
        artifact = dataclass_artifact()
        with tempfile.TemporaryDirectory(prefix="pyz80-generated-adapters-") as raw:
            root = Path(raw).resolve()
            _fixture(root)  # Synthetic correlated upstream reports; no live claim.
            build = root / "Build"
            vm_path = build / "rtype_python_whole_program_vm_status.json"
            status = json.loads(vm_path.read_bytes())
            digest = hashlib.sha256(artifact.target_bytecode).hexdigest()
            status.update({"artifact_semantic_sha256": artifact.semantic_sha256,
                           "function_id_table": artifact.function_ids,
                           "adapter_table": list(artifact.adapter_table),
                           "target_bytecode": {"sha256": digest, "bytes": len(artifact.target_bytecode)}})
            vm_path.write_text(json.dumps(status))
            stack_path = build / "rtype_python_whole_program_vm_stack_bound_status.json"
            stack = json.loads(stack_path.read_bytes())
            stack["binding"].update({"artifact_semantic_sha256": artifact.semantic_sha256,
                                     "target_bytecode_sha256": digest})
            stack_path.write_text(json.dumps(stack))
            (build / "rtype_python_whole_program_vm.bin").write_bytes(artifact.target_bytecode)
            write_translation_checkpoint(root)
            report = generate(root, build_directory=build, source_directory=build)
            self.assertEqual(report["coverage"]["dataclass_field_key_count"], 2)
            for name in ("pyz80_whole_program_vm.h", "pyz80_target_object_runtime.h"):
                shutil.copy2(RUNTIME / name, build / name)
            (build / "check.c").write_text('''
#include "pyz80_target_adapter_plan_generated.h"
int main(void) {
    PyZ80TargetContext context = {0};
    PyZ80Generated_Bind(&context);
    if (context.adapters != PyZ80GeneratedAdapters ||
        context.adapter_count != PYZ80_GENERATED_ADAPTER_COUNT ||
        context.operators != PyZ80GeneratedOperators ||
        context.operator_count != PYZ80_GENERATED_OPERATOR_COUNT ||
        context.field_keys != PyZ80GeneratedFieldKeys ||
        context.field_key_count != 2 ||
        context.dispatch_functions != PyZ80GeneratedDispatchFunctions ||
        context.dispatch_function_count != PYZ80_GENERATED_DISPATCH_WORD_COUNT ||
        context.function_count != PYZ80_GENERATED_FUNCTION_COUNT) return 1;
    return 0;
}
''')
            compiled = subprocess.run(
                [str(TCC), "-std=c11", "-Wall", "-Werror", "-o", "check.exe",
                 "check.c", "pyz80_target_adapter_plan_generated.c"],
                cwd=build, capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            self.assertEqual(subprocess.run([str(build / "check.exe")], timeout=30).returncode, 0)
            environment = os.environ.copy()
            environment["PATH"] = str(SDCC.parent) + os.pathsep + environment.get("PATH", "")
            compiled = subprocess.run(
                [str(SDCC), "-mz80", "--std-c11", "--sdcccall", "1", "--stack-auto",
                 "--opt-code-speed", "-c", "pyz80_target_adapter_plan_generated.c"],
                cwd=build, env=environment, capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            self.assertIn("A _DATA size 0 ", (build / "pyz80_target_adapter_plan_generated.rel").read_text())


if __name__ == "__main__":
    unittest.main()
