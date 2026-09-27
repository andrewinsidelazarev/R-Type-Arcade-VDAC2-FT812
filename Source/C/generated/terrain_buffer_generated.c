#include "terrain_buffer_generated.h"
static uint8_t Terrain_ApplyStrip_unpack_0(PyBufferSpan *buffer,int32_t offset,int32_t *values) {
    uint16_t position;
    uint8_t error;
    error=PyBuf_Range(buffer,offset,4,&position);
    if(error) return error;
    values[0]=PyBuf_Read(buffer,position+0,2,0,0);
    values[1]=PyBuf_Read(buffer,position+2,2,0,0);
    return 0;
}
static uint8_t Terrain_ApplyStrip_pack_0(PyBufferSpan *buffer,int32_t offset,int32_t *values) {
    uint16_t position;
    uint8_t error;
    if(!buffer->writable) return PYBUF_READONLY;
    error=PyBuf_Range(buffer,offset,4,&position);
    if(error) return error;
    error=PyBuf_Write(buffer,position+0,2,0,0,values[0]);
    if(error) return error;
    error=PyBuf_Write(buffer,position+2,2,0,0,values[1]);
    if(error) return error;
    return 0;
}
PY_BUFFER_API uint8_t Terrain_ApplyStrip(PyBufferFault *pybuf_fault,PyBufferSpan *vram,int32_t destination,PyBufferSpan *strip) {
    int32_t attribute;
    int32_t base;
    int32_t code;
    int32_t column;
    int32_t cursor;
    int32_t output;
    int32_t pybuf_loop_1;
    int32_t pybuf_loop_2;
    int32_t row;
    uint8_t pybuf_error;
    int32_t pybuf_values[2];
    pybuf_fault->error=0; pybuf_fault->line=0;
    /* Python: строка 86; If. */
    if (((((int32_t)strip->size) != 960L))) {
        /* Python: строка 87. */
        return PyBuf_Fail(pybuf_fault,PYBUF_SOURCE_VALUE,87);
    }
    /* Python: строка 88; Assign. */
    base = (((destination * 2L) + 4128L) & 4351L); /* Вычислить, затем записать. */
    /* Python: строка 89; Assign. */
    cursor = 0L; /* Вычислить, затем записать. */
    /* Python: строка 90. */
    for(pybuf_loop_1=0; pybuf_loop_1<30; ++pybuf_loop_1) {
        row=pybuf_loop_1;
        /* Python: строка 91; Assign. */
        output = (base + (row * 256L)); /* Вычислить, затем записать. */
        /* Доказанный непрерывный цикл; иначе исходный путь. */
        if(PyBuf_TryCopyRun(strip,cursor,vram,output,32)) {
            cursor+=32L; column=7L;
        } else {
        /* Python: строка 92. */
            for(pybuf_loop_2=0; pybuf_loop_2<8; ++pybuf_loop_2) {
                column=pybuf_loop_2;
                /* Python: строка 93. */
                pybuf_error=Terrain_ApplyStrip_unpack_0(strip,cursor,pybuf_values);
                if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,93);
                code=pybuf_values[0];
                attribute=pybuf_values[1];
                /* Python: строка 94. */
                pybuf_values[0]=code;
                pybuf_values[1]=attribute;
                pybuf_error=Terrain_ApplyStrip_pack_0(vram,(output + (column * 4L)),pybuf_values);
                if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,94);
                /* Python: строка 96; AugAssign. */
                cursor = (cursor + 4L); /* Вычислить, затем записать. */
            }
        }
    }
    return 1;
}
