#include "tilemap_buffer_probe_generated.h"
static uint8_t Buffer_CopyWord_unpack_0(PyBufferView *buffer,int32_t offset,int32_t *values) {
    uint32_t position;
    uint8_t error;
    error=PyView_Range(buffer,offset,4,&position);
    if(error) return error;
    error=PyView_Read(buffer,position+0,4,0,1,&values[0]);
    if(error) return error;
    return 0;
}
static uint8_t Buffer_CopyWord_pack_0(PyBufferView *buffer,int32_t offset,int32_t *values) {
    uint32_t position;
    uint8_t error;
    if(!buffer->writable) return PYBUF_READONLY;
    error=PyView_Range(buffer,offset,4,&position);
    if(error) return error;
    error=PyView_Write(buffer,position+0,4,0,1,values[0]);
    if(error) return error;
    return 0;
}
static uint8_t Buffer_CopyWord_unpack_1(PyBufferView *buffer,int32_t offset,int32_t *values) {
    uint32_t position;
    uint8_t error;
    error=PyView_Range(buffer,offset,4,&position);
    if(error) return error;
    error=PyView_Read(buffer,position+0,4,1,1,&values[0]);
    if(error) return error;
    return 0;
}
static uint8_t Buffer_CopyWord_pack_1(PyBufferView *buffer,int32_t offset,int32_t *values) {
    uint32_t position;
    uint8_t error;
    if(!buffer->writable) return PYBUF_READONLY;
    error=PyView_Range(buffer,offset,4,&position);
    if(error) return error;
    error=PyView_Write(buffer,position+0,4,1,1,values[0]);
    if(error) return error;
    return 0;
}
PY_BUFFER_API uint8_t Buffer_CopyWord(PyBufferFault *pybuf_fault,PyBufferView *src,PyBufferView *dst,int32_t read,int32_t write) {
    int32_t value;
    uint8_t pybuf_error;
    int32_t pybuf_values[1];
    pybuf_fault->error=0; pybuf_fault->line=0;
    /* Python: строка 2. */
    pybuf_error=Buffer_CopyWord_unpack_0(src,read,pybuf_values);
    if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,2);
    value=pybuf_values[0];
    /* Python: строка 3. */
    pybuf_values[0]=value;
    pybuf_error=Buffer_CopyWord_pack_1(dst,write,pybuf_values);
    if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,3);
    return 1;
}
