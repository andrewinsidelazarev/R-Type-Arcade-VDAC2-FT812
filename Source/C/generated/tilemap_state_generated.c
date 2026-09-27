#include "tilemap_state_generated.h"

PY_AGGREGATE_API uint8_t TilemapState__crossing(PyBufferFault *pybuf_fault,TilemapState *record,int32_t layer,int32_t old,int32_t new) {
    int32_t new_x;
    int32_t old_x;
    int32_t pyagg_tmp_1;
    int32_t pyagg_tmp_2;
    int32_t pyagg_tmp_3;
    int32_t pyagg_tmp_4;
    int32_t pyagg_tmp_5;
    uint8_t pybuf_error;
    int32_t pybuf_values[16];
    pybuf_fault->error=0; pybuf_fault->line=0;
    /* Python: строка 334; Assign. */
    pyagg_tmp_1=((old >> 8L) & 511L);
    old_x=pyagg_tmp_1; /* MOV после вычисления RHS. */
    /* Python: строка 335; Assign. */
    pyagg_tmp_2=((new >> 8L) & 511L);
    new_x=pyagg_tmp_2; /* MOV после вычисления RHS. */
    /* Python: строка 336; If. */
    if((((old_x & 64L) != (new_x & 64L)))) {
        /* Python: строка 337; Assign. */
        pyagg_tmp_3=layer;
        if(pyagg_tmp_3<0) pyagg_tmp_3+=2L;
        if(pyagg_tmp_3<0 || pyagg_tmp_3>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,337);
        pyagg_tmp_4=((record->target[(uint16_t)pyagg_tmp_3] + 16L) & 255L);
        pyagg_tmp_5=layer;
        if(pyagg_tmp_5<0) pyagg_tmp_5+=2L;
        if(pyagg_tmp_5<0 || pyagg_tmp_5>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,337);
        record->target[(uint16_t)pyagg_tmp_5]=pyagg_tmp_4; /* MOV после вычисления RHS. */
    }
    return 1;
}


static uint8_t TilemapState_advance_set_0(int32_t value) {
    return value==4397L || value==4432L || value==4463L || value==4466L || value==4468L || value==4470L || value==4503L || value==14222L || value==14225L || value==14228L || value==14231L || value==14234L || value==14237L || value==14240L || value==14259L || value==14420L || value==14655L || value==16164L || value==16499L;
}
PY_AGGREGATE_API uint8_t TilemapState_advance(PyBufferFault *pybuf_fault,TilemapState *record,const StageScroll *scroll) {
    int32_t layer;
    int32_t new;
    int32_t old;
    int32_t pyagg_tmp_1;
    int32_t pyagg_tmp_10;
    int32_t pyagg_tmp_11;
    int32_t pyagg_tmp_12;
    int32_t pyagg_tmp_2;
    int32_t pyagg_tmp_3;
    int32_t pyagg_tmp_4;
    int32_t pyagg_tmp_5;
    int32_t pyagg_tmp_6;
    int32_t pyagg_tmp_7;
    int32_t pyagg_tmp_8;
    int32_t pyagg_tmp_9;
    int32_t velocities[2];
    int32_t accumulators[2];
    uint8_t pybuf_error;
    int32_t pybuf_values[16];
    pybuf_fault->error=0; pybuf_fault->line=0;
    /* Python: строка 342; If. */
    if(TilemapState_advance_set_0(scroll->vblank)) {
        /* Python: строка 343; Return. */
        return 1;
    }
    /* Python: строка 344; Assign. */
    pyagg_tmp_1=scroll->foreground_velocity;
    pyagg_tmp_2=scroll->background_velocity;
    velocities[0]=pyagg_tmp_1;
    velocities[1]=pyagg_tmp_2;
    /* Python: строка 345; Assign. */
    pyagg_tmp_3=scroll->foreground_accumulator;
    pyagg_tmp_4=scroll->background_accumulator;
    accumulators[0]=pyagg_tmp_3;
    accumulators[1]=pyagg_tmp_4;
    /* Python: строка 347; For. */
    for(pyagg_tmp_5=0;pyagg_tmp_5<2L;++pyagg_tmp_5) {
        layer=pyagg_tmp_5;
        /* Python: строка 348; Assign. */
        pyagg_tmp_6=layer;
        if(pyagg_tmp_6<0) pyagg_tmp_6+=2L;
        if(pyagg_tmp_6<0 || pyagg_tmp_6>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,348);
        pyagg_tmp_7=accumulators[(uint16_t)pyagg_tmp_6];
        old=pyagg_tmp_7; /* MOV после вычисления RHS. */
        /* Python: строка 349; Assign. */
        pyagg_tmp_8=layer;
        if(pyagg_tmp_8<0) pyagg_tmp_8+=2L;
        if(pyagg_tmp_8<0 || pyagg_tmp_8>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,349);
        pyagg_tmp_9=((old + velocities[(uint16_t)pyagg_tmp_8]) & 131071L);
        new=pyagg_tmp_9; /* MOV после вычисления RHS. */
        /* Python: строка 350; Expr. */
        pyagg_tmp_10=layer;
        pyagg_tmp_11=old;
        pyagg_tmp_12=new;
        if(!TilemapState__crossing(pybuf_fault,record,pyagg_tmp_10,pyagg_tmp_11,pyagg_tmp_12)) return 0;
    }
    /* Python: строка 351; Expr. */
    if(!TilemapState__pump(pybuf_fault,record)) return 0;
    return 1;
}


PY_AGGREGATE_API uint8_t TilemapState__pump(PyBufferFault *pybuf_fault,TilemapState *record) {
    int32_t layer;
    int32_t pyagg_tmp_1;
    int32_t pyagg_tmp_10;
    int32_t pyagg_tmp_11;
    int32_t pyagg_tmp_12;
    int32_t pyagg_tmp_13;
    int32_t pyagg_tmp_14;
    int32_t pyagg_tmp_2;
    int32_t pyagg_tmp_3;
    int32_t pyagg_tmp_4;
    int32_t pyagg_tmp_5;
    int32_t pyagg_tmp_6;
    int32_t pyagg_tmp_7;
    int32_t pyagg_tmp_8;
    int32_t pyagg_tmp_9;
    uint8_t pybuf_error;
    int32_t pybuf_values[16];
    pybuf_fault->error=0; pybuf_fault->line=0;
    /* Python: строка 354; For. */
    for(pyagg_tmp_1=0;pyagg_tmp_1<2L;++pyagg_tmp_1) {
        layer=pyagg_tmp_1;
        /* Python: строка 355; If. */
        pyagg_tmp_2=layer;
        if(pyagg_tmp_2<0) pyagg_tmp_2+=2L;
        if(pyagg_tmp_2<0 || pyagg_tmp_2>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,355);
        pyagg_tmp_3=layer;
        if(pyagg_tmp_3<0) pyagg_tmp_3+=2L;
        if(pyagg_tmp_3<0 || pyagg_tmp_3>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,355);
        if(((record->tracker[(uint16_t)pyagg_tmp_2] == record->target[(uint16_t)pyagg_tmp_3]))) {
            /* Python: строка 356; Continue. */
            continue;
        }
        /* Python: строка 357; Expr. */
        pyagg_tmp_4=layer;
        pyagg_tmp_6=layer;
        if(pyagg_tmp_6<0) pyagg_tmp_6+=2L;
        if(pyagg_tmp_6<0 || pyagg_tmp_6>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,357);
        pyagg_tmp_5=record->source[(uint16_t)pyagg_tmp_6];
        pyagg_tmp_8=layer;
        if(pyagg_tmp_8<0) pyagg_tmp_8+=2L;
        if(pyagg_tmp_8<0 || pyagg_tmp_8>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,357);
        pyagg_tmp_7=record->tracker[(uint16_t)pyagg_tmp_8];
        if(!TilemapState__draw_strip(pybuf_fault,record,pyagg_tmp_4,pyagg_tmp_5,pyagg_tmp_7)) return 0;
        /* Python: строка 358; Assign. */
        pyagg_tmp_9=layer;
        if(pyagg_tmp_9<0) pyagg_tmp_9+=2L;
        if(pyagg_tmp_9<0 || pyagg_tmp_9>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,358);
        pyagg_tmp_10=((record->tracker[(uint16_t)pyagg_tmp_9] + 16L) & 255L);
        pyagg_tmp_11=layer;
        if(pyagg_tmp_11<0) pyagg_tmp_11+=2L;
        if(pyagg_tmp_11<0 || pyagg_tmp_11>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,358);
        record->tracker[(uint16_t)pyagg_tmp_11]=pyagg_tmp_10; /* MOV после вычисления RHS. */
        /* Python: строка 359; Assign. */
        pyagg_tmp_12=layer;
        if(pyagg_tmp_12<0) pyagg_tmp_12+=2L;
        if(pyagg_tmp_12<0 || pyagg_tmp_12>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,359);
        pyagg_tmp_13=((record->source[(uint16_t)pyagg_tmp_12] + 10L) & 65535L);
        pyagg_tmp_14=layer;
        if(pyagg_tmp_14<0) pyagg_tmp_14+=2L;
        if(pyagg_tmp_14<0 || pyagg_tmp_14>=2L) return PyBuf_Fail(pybuf_fault,PYBUF_INDEX,359);
        record->source[(uint16_t)pyagg_tmp_14]=pyagg_tmp_13; /* MOV после вычисления RHS. */
    }
    return 1;
}

static uint8_t TilemapState_state_unpack_0(PyBufferView *buffer,int32_t offset,int32_t *values) {
    uint32_t position;
    uint8_t error;
    error=PyView_Range(buffer,offset,4,&position);
    if(error) return error;
    error=PyView_Read(buffer,position+0,2,0,0,&values[0]);
    if(error) return error;
    error=PyView_Read(buffer,position+2,2,0,0,&values[1]);
    if(error) return error;
    return 0;
}
static uint8_t TilemapState_state_pack_0(PyBufferView *buffer,int32_t offset,int32_t *values) {
    uint32_t position;
    uint8_t error;
    if(!buffer->writable) return PYBUF_READONLY;
    error=PyView_Range(buffer,offset,4,&position);
    if(error) return error;
    error=PyView_Write(buffer,position+0,2,0,0,values[0]);
    if(error) return error;
    error=PyView_Write(buffer,position+2,2,0,0,values[1]);
    if(error) return error;
    return 0;
}
PY_AGGREGATE_API uint8_t TilemapState_state(PyBufferFault *pybuf_fault,TilemapState *record,int32_t layer,int32_t row,int32_t column,int32_t *result) {
    int32_t cell;
    int32_t pyagg_result_0;
    int32_t pyagg_result_1;
    int32_t pyagg_tmp_1;
    uint8_t pybuf_error;
    int32_t pybuf_values[16];
    PyBufferView *pybuf_selected_0;
    pybuf_fault->error=0; pybuf_fault->line=0;
    /* Python: строка 392; Assign. */
    pyagg_tmp_1=(((row + 16L) * 64L) + column);
    cell=pyagg_tmp_1; /* MOV после вычисления RHS. */
    /* Python: строка 393; Return. */
    /* Python: строка 393. */
    pybuf_error=PyView_Index((&record->vram),layer,&pybuf_selected_0);
    if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,393);
    pybuf_error=TilemapState_state_unpack_0(pybuf_selected_0,(cell * 4L),pybuf_values);
    if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,393);
    pyagg_result_0=pybuf_values[0];
    pyagg_result_1=pybuf_values[1];
    result[0]=pyagg_result_0;
    result[1]=pyagg_result_1;
    return 1;
    return 1;
}
