"""No persistent near pointers: PZTB generator and native paging/VM tests."""
from __future__ import annotations

import struct
import unittest
import zlib

from generate_pzvt_target_adapters import build_adapter_specs
from pyz80_compiler.banked_tables import build_banked_tables, TABLES
from test_pyz80_banked_fixture import banked_fixture
from test_pyz80_callable_runtime import compile_run, PRELUDE, TCC
from test_pyz80_import_runtime import import_check

PROOF='17'*32


def big_plan():
    plan=build_adapter_specs([],[],[])
    plan.update(specs=[('PYZ80_TARGET_UNSUPPORTED',i%255,i) for i in range(19000)],
                field_keys=list(range(40000)),dispatch_functions=[3,1,2,3],function_count=6000,
                positional_call_flags=[i%2 for i in range(19000)],
                call_signatures=[(i,2,2,0,1) for i in range(6000)],parameter_names=list(range(6002)),
                call_layout_offsets=[65535]*19000,call_layout_keys=[65535,7,8],class_body_flags=[i%2 for i in range(6000)])
    return plan,[2]*6000


class BankedTablesTests(unittest.TestCase):
    def test_binary_directory_and_large_offsets_are_exact(self):
        plan,arities=big_plan()
        blob,header,code,report=build_banked_tables(plan,arities,PROOF)
        self.assertEqual(len(blob),report['bytes'])
        self.assertEqual(zlib.crc32(blob),int(report['crc32'],16))
        self.assertEqual(blob[:4],b'PZTB')
        self.assertEqual(blob[12:44],bytes.fromhex(PROOF))
        self.assertLess(len(code),3000)
        self.assertNotIn('PyZ80GeneratedAdapters[',code)
        self.assertGreater(report['bytes'],65536)
        for row,(name,fmt) in zip(report['tables'],TABLES):
            self.assertEqual(struct.unpack_from('<IH',blob,44+row['id']*6),(row['offset'],row['count']))
            self.assertEqual(row['record_bytes'],struct.calcsize('<'+fmt))
        fields=report['tables'][1]['offset']
        self.assertGreater(fields,65536)
        self.assertEqual(struct.unpack_from('<H',blob,fields+39999*2)[0],39999)

    def test_generator_rejects_truncation_unknown_ops_and_mismatched_counts(self):
        base=build_adapter_specs([],[],[])
        for changes in ({'function_count':65536}, {'function_count':1}, {'field_keys':[65536]},
                        {'field_keys':[-1]}, {'field_keys':[True]}, {'field_keys':[0]*65536},
                        {'specs':[('GUESS',0,0)],'positional_call_flags':[0],'call_layout_offsets':[65535]},
                        {'class_body_flags':[0]}):
            with self.subTest(changes=tuple(changes)),self.assertRaises(ValueError):
                build_banked_tables(dict(base,**changes),[],PROOF)
        for proof in ('','00'*31,'GG'*32):
            with self.assertRaises(ValueError):build_banked_tables(base,[],proof)

    @unittest.skipUnless(TCC,'host compiler unavailable')
    def test_flat_host_oracle_keeps_32_bit_table_offsets(self):
        compile_run(PRELUDE+r'''
int main(void) {
    PyZ80TargetContext objects;static uint16_t fields[40000];uint16_t value;
    PyZ80Target_Init(&objects,0,0,0,0,0,0,0,0,0,0,0,0);
    fields[32767]=17;fields[32768]=18;fields[39999]=19;
    objects.field_keys=fields;objects.field_key_count=40000;
    CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_FIELDS,32767,&value) && value==17);
    CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_FIELDS,32768,&value) && value==18);
    CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_FIELDS,39999,&value) && value==19);
    CHECK(!PyZ80Target_ReadWord(&objects,PYZ80_TABLE_FIELDS,40000,&value));
    return 0;
}
''')

    @unittest.skipUnless(TCC,'host compiler unavailable')
    def test_native_large_tables_copy_across_pages_and_fail_closed(self):
        plan,arities=big_plan()
        blob,h,c,report=build_banked_tables(plan,arities,PROOF)
        compile_run(PRELUDE+'\n#include "pyz80_target_banked_plan_generated.h"\n'+banked_fixture(blob)+r'''
int main(void) {
    PyZ80TargetContext objects,before;PyZ80TargetBankedTables tables,saved;
    PyZ80VM vm;PyZ80VMImage image;
    PyZ80TargetAdapterSpec spec,retained;PyZ80TargetCallSignature signature;
    uint8_t proof[32],flag,bytes[20],old;uint16_t keys[254],word,i;
    unsigned maps,restores;
    memset(proof,0x17,32);memset(&vm,0,sizeof(vm));memset(&tables,0xA5,sizeof(tables));
    vm.status=PYZ80_VM_IDLE;vm.header.adapter_count=19000;vm.header.function_count=6000;
    vm.image.expected_proof_sha256=proof;
    PyZ80Target_Init(&objects,0,0,0,0,0,0,0,0,0,0,0,0);
    bank_init();before=objects;saved=tables;
    /* Structural failure, CRC failure, reader failure: no partially bound state. */
    bank_source[44]++;CHECK(!PyZ80Generated_BindBanked(&objects,&vm,&tables,PyZ80Banked_Read,&bank_image,keys,254));bank_source[44]--;
    old=bank_source[110];bank_source[110]^=1;
    CHECK(!PyZ80Generated_BindBanked(&objects,&vm,&tables,PyZ80Banked_Read,&bank_image,keys,254));bank_source[110]=old;
    fail_map=1;CHECK(!PyZ80Generated_BindBanked(&objects,&vm,&tables,PyZ80Banked_Read,&bank_image,keys,254));fail_map=0;
    proof[0]++;CHECK(!PyZ80Generated_BindBanked(&objects,&vm,&tables,PyZ80Banked_Read,&bank_image,keys,254));proof[0]--;
    vm.header.function_count--;CHECK(!PyZ80Generated_BindBanked(&objects,&vm,&tables,PyZ80Banked_Read,&bank_image,keys,254));vm.header.function_count++;
    CHECK(!memcmp(&before,&objects,sizeof(objects)) && !memcmp(&saved,&tables,sizeof(tables)));
    CHECK(!PyZ80Generated_BindBanked(&objects,&vm,&tables,PyZ80Banked_Read,&bank_image,(uint16_t *)&objects,254));
    CHECK(PyZ80Generated_BindBanked(&objects,&vm,&tables,PyZ80Banked_Read,&bank_image,keys,254));
    CHECK(!objects.adapters && !objects.field_keys && !objects.call_signatures);
    CHECK(!PyZ80Generated_BindBanked(&objects,&vm,&tables,PyZ80Banked_Read,&bank_image,keys,254));
    for(i=0;i<19000;++i) {
        CHECK(PyZ80Target_ReadAdapter(&objects,i,&spec));
        CHECK(spec.operation==0 && spec.argument_count==i%255 && spec.auxiliary==i);
        retained=spec;
        CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_FIELDS,i,&word) && word==i);
        CHECK(!memcmp(&spec,&retained,sizeof(spec)));
        CHECK(PyZ80Target_ReadByte(&objects,PYZ80_TABLE_CALL_FLAGS,i,&flag) && flag==i%2);
        CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_CALL_OFFSETS,i,&word) && word==65535);
    }
    for(i=0;i<6000;++i) {
        CHECK(PyZ80Target_ReadSignature(&objects,i,&signature) && signature.start==i && signature.count==2 && signature.supported==1);
        CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_ARITIES,i,&word) && word==2);
        CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_PARAMETERS,i,&word) && word==i);
        CHECK(PyZ80Target_ReadByte(&objects,PYZ80_TABLE_CLASS_FLAGS,i,&flag) && flag==i%2);
    }
    CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_DISPATCH,3,&word) && word==3);
    CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_CALL_KEYS,2,&word) && word==8);
    CHECK(PyZ80Target_ReadWord(&objects,PYZ80_TABLE_FIELDS,39999,&word) && word==39999);
    maps=bank_maps;CHECK(!PyZ80Target_ReadWord(&objects,PYZ80_TABLE_FIELDS,40000,&word) && maps==bank_maps);
    CHECK(!PyZ80Target_ReadWord(&objects,PYZ80_TABLE_ADAPTERS,0,&word));
    CHECK(!PyZ80Target_ReadByte(&objects,PYZ80_TABLE_FIELDS,0,&flag));
    CHECK(!PyZ80Target_ReadTable(&objects,10,0,&word));
    /* Read failure cannot leak half a decoded record. */
    retained=spec;fail_map=1;CHECK(!PyZ80Target_ReadAdapter(&objects,0,&spec));fail_map=0;
    CHECK(!memcmp(&spec,&retained,sizeof(spec)));
    maps=bank_maps;restores=bank_restores;
    CHECK(PyZ80Banked_Read(&bank_image,65530,bytes,20));
    CHECK(!memcmp(bytes,bank_source+65530,20) && bank_maps==maps+2 && bank_restores==restores+2);
    reenter=1;CHECK(PyZ80Banked_Read(&bank_image,0,bytes,20));reenter=0;
    CHECK(!PyZ80Banked_Read(&bank_image,0,bank_window,20));
    CHECK(!PyZ80Banked_Read(&bank_image,0,(uint8_t *)&bank_image,1));
    CHECK(!PyZ80Banked_Read(&bank_image,0xffffffffUL,bytes,1));
    CHECK(!PyZ80Banked_Read(&bank_image,sizeof(bank_source)-1,bytes,2));
    bank_image.first_page=255;CHECK(!PyZ80Banked_Read(&bank_image,0,bytes,1));bank_image.first_page=7;
    fail_restore=1;CHECK(!PyZ80Banked_Read(&bank_image,0,bytes,1));fail_restore=0;
    CHECK(current_bank==3 && bank_maps==bank_restores && !bank_image.busy);
    return 0;
}
''', banked=True, extra_sources={'pyz80_target_banked_plan_generated.h':h,'pyz80_target_banked_plan_generated.c':c})

    @unittest.skipUnless(TCC,'host compiler unavailable')
    def test_module_closures_keywords_classes_super_and_gc_match_python(self):
        import_check({'app': '''from a import make, Child
f=make(7)
obj=Child(8)
answer=0
for i in range(80):
    answer=answer+f(y=i)+obj.step(amount=2)
''','a': '''def make(x):
    def inner(y=3):
        return x+y
    return inner
class Base:
    def __init__(self,x):
        self.x=x
    def step(self,amount=1):
        self.x=self.x+amount
        return self.x
class Child(Base):
    def step(self,amount=1):
        return super().step(amount=amount)+1
'''},classes=True,banked=True,max_slices=30000)

    @unittest.skipUnless(TCC,'host compiler unavailable')
    def test_table_io_error_is_not_an_external_provider_fallback(self):
        import_check({'app':'answer=7\n'},banked=True,expect_vm_error=True,
                     before_slice='fail_map=1;',after='fail_map=0;CHECK(vm.error==PYZ80_VM_E_ADAPTER);')

    @unittest.skipUnless(TCC,'host compiler unavailable')
    def test_provider_and_gc_scratch_cannot_overwrite_bank_state(self):
        import_check({'app':'class A:\n    pass\na=A()\nanswer=7\n'},banked=True,classes=True,
            after_attach=r'''
CHECK(!PyZ80Target_AttachScopes((PyZ80TargetScopes *)&bank_tables,&objects,&vm,closures,DEPTH,globals,FUNCTIONS));
CHECK(!PyZ80Target_AttachCallBinding(&scopes,(PyZ80VMValue *)bank_keys,MAX_ARGS));
CHECK(!PyZ80Target_AttachImports((PyZ80TargetImports *)&bank_tables,&scopes,&PyZ80GeneratedImportPlan,modules,states,globals,frames,DEPTH));
CHECK(!PyZ80Target_AttachClasses((PyZ80TargetClasses *)&bank_tables,&scopes,class_frames,class_roots,DEPTH,class_routes));
''', before_slice=r'''
{
PyZ80TargetGC bad=gc;PyZ80TargetBankedTables saved=bank_tables;
bad.marked=(uint8_t *)&bank_tables;
CHECK(!PyZ80Target_Collect(&objects,&vm,&scopes,modules,MODULES,&bad));
CHECK(!memcmp(&saved,&bank_tables,sizeof(saved)));
}
''')

    @unittest.skipUnless(TCC,'host compiler unavailable')
    def test_bulk_fields_are_atomic_when_a_later_banked_key_read_fails(self):
        plan=build_adapter_specs([],['x','y'],[])
        plan.update(specs=[('PYZ80_TARGET_STORE_DATACLASS_FIELDS',3,0)],field_keys=[0,1],
                    positional_call_flags=[0],call_layout_offsets=[65535])
        blob,h,c,_=build_banked_tables(plan,[],PROOF)
        compile_run(PRELUDE+'\n#include "pyz80_target_banked_plan_generated.h"\n'+banked_fixture(blob)+r'''
static PyZ80TargetTableRead reader;
static uint8_t reject_second(void *context,uint8_t table,uint16_t index,void *record) {
    return table==PYZ80_TABLE_FIELDS && index==1 ? 0 : reader(context,table,index,record);
}
int main(void) {
    PyZ80TargetContext objects;PyZ80TargetBankedTables tables;
    PyZ80VM vm;uint8_t proof[32];uint16_t keys[2];
    PyZ80TargetNode nodes[2];PyZ80TargetField fields[4];PyZ80VMValue args[3],result;
    memset(&vm,0,sizeof(vm));memset(proof,0x17,32);vm.image.expected_proof_sha256=proof;
    vm.status=PYZ80_VM_IDLE;vm.header.adapter_count=1;
    PyZ80Target_Init(&objects,nodes,2,fields,4,0,0,0,0,0,0,0,0);
    bank_init();CHECK(PyZ80Generated_BindBanked(&objects,&vm,&tables,PyZ80Banked_Read,&bank_image,keys,2));
    CHECK(PyZ80Target_AllocateNode(&objects,PYZ80_TARGET_NODE_OBJECT,65535,&args[0]));
    args[1]=integer(7);args[2]=integer(9);reader=objects.table_read;objects.table_read=reject_second;
    CHECK(!PyZ80Target_Invoke(&objects,&vm,0,0,args,3,0,&result));
    CHECK(objects.field_used==0 && nodes[0].field_head==0);
    objects.table_read=reader;objects.table_key_capacity=1;
    CHECK(!PyZ80Target_Invoke(&objects,&vm,0,0,args,3,0,&result));CHECK(objects.field_used==0);
    objects.table_key_capacity=2;CHECK(PyZ80Target_Invoke(&objects,&vm,0,0,args,3,0,&result));
    CHECK(PyZ80Target_LoadField(&objects,&args[0],0,&result) && result.payload==7);
    CHECK(PyZ80Target_LoadField(&objects,&args[0],1,&result) && result.payload==9);
    CHECK(bank_maps==bank_restores && current_bank==3);
    return 0;
}
''',banked=True,extra_sources={'pyz80_target_banked_plan_generated.h':h,'pyz80_target_banked_plan_generated.c':c})


if __name__=='__main__':unittest.main()
