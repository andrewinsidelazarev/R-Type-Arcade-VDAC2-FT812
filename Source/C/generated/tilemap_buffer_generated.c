#include "tilemap_buffer_generated.h"
static uint8_t Tilemaps_DrawStrip_unpack_0(PyBufferView *buffer,int32_t offset,int32_t *values) {
    uint32_t position;
    uint8_t error;
    error=PyView_Range(buffer,offset,2,&position);
    if(error) return error;
    error=PyView_Read(buffer,position+0,2,0,0,&values[0]);
    if(error) return error;
    return 0;
}
static uint8_t Tilemaps_DrawStrip_pack_0(PyBufferView *buffer,int32_t offset,int32_t *values) {
    uint32_t position;
    uint8_t error;
    if(!buffer->writable) return PYBUF_READONLY;
    error=PyView_Range(buffer,offset,2,&position);
    if(error) return error;
    error=PyView_Write(buffer,position+0,2,0,0,values[0]);
    if(error) return error;
    return 0;
}
static uint8_t Tilemaps_DrawStrip_unpack_1(PyBufferView *buffer,int32_t offset,int32_t *values) {
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
static uint8_t Tilemaps_DrawStrip_pack_1(PyBufferView *buffer,int32_t offset,int32_t *values) {
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
PY_BUFFER_API uint8_t Tilemaps_DrawStrip(PyBufferFault *pybuf_fault,PyBufferView *pybuf_field_0,PyBufferViewArray *pybuf_field_1,int32_t layer,int32_t source,int32_t destination) {
    int32_t _;
    int32_t attribute;
    int32_t base_di;
    int32_t bias;
    int32_t code;
    int32_t descriptor;
    int32_t descriptors;
    int32_t flip_x;
    int32_t flip_y;
    int32_t metatile;
    int32_t output;
    int32_t output_step;
    int32_t pybuf_loop_1;
    int32_t pybuf_loop_2;
    int32_t pybuf_loop_3;
    int32_t row;
    int32_t row_start;
    int32_t row_step;
    int32_t source_offset;
    PyBufferView *pybuf_selected_0;
    uint8_t pybuf_error;
    int32_t pybuf_values[2];
    pybuf_fault->error=0; pybuf_fault->line=0;
    /* Python: строка 363; Assign. */
    bias = (((layer == 0L)) ? 14809L : 10609L); /* Вычислить, затем записать. */
    /* Python: строка 364; Assign. */
    descriptors = (65536L + ((source - bias) & 65535L)); /* Вычислить, затем записать. */
    /* Python: строка 365; Assign. */
    base_di = (((destination * 2L) + 4128L) & 4351L); /* Вычислить, затем записать. */
    /* Python: строка 366. */
    for(pybuf_loop_1=0; pybuf_loop_1<5; ++pybuf_loop_1) {
        metatile=pybuf_loop_1;
        /* Python: строка 367. */
        pybuf_error=Tilemaps_DrawStrip_unpack_0(pybuf_field_0,(descriptors + (metatile * 2L)),pybuf_values);
        if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,367);
        descriptor=pybuf_values[0];
        /* Python: строка 369; Assign. */
        source_offset = (196608L + ((descriptor & 16383L) * 144L)); /* Вычислить, затем записать. */
        /* Python: строка 370; Assign. */
        flip_x = (((descriptor & 16384L)) != 0); /* Вычислить, затем записать. */
        /* Python: строка 371; Assign. */
        flip_y = (((descriptor & 32768L)) != 0); /* Вычислить, затем записать. */
        /* Python: строка 372; Assign. */
        row_start = (base_di + (flip_y ? 1280L : 0L)); /* Вычислить, затем записать. */
        /* Python: строка 373; Assign. */
        row_step = (flip_y ? (-256L) : 256L); /* Вычислить, затем записать. */
        /* Python: строка 374. */
        for(pybuf_loop_2=0; pybuf_loop_2<6; ++pybuf_loop_2) {
            row=pybuf_loop_2;
            /* Python: строка 375; Assign. */
            output = ((row_start + (row * row_step)) + (flip_x ? 28L : 0L)); /* Вычислить, затем записать. */
            /* Python: строка 376; Assign. */
            output_step = (flip_x ? (-4L) : 4L); /* Вычислить, затем записать. */
            /* Python: строка 377. */
            for(pybuf_loop_3=0; pybuf_loop_3<8; ++pybuf_loop_3) {
                _=pybuf_loop_3;
                /* Python: строка 378. */
                pybuf_error=Tilemaps_DrawStrip_unpack_0(pybuf_field_0,source_offset,pybuf_values);
                if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,378);
                code=pybuf_values[0];
                /* Python: строка 379. */
                pybuf_error=Tilemaps_DrawStrip_unpack_0(pybuf_field_0,(source_offset + 2L),pybuf_values);
                if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,379);
                attribute=pybuf_values[0];
                /* Python: строка 381; AugAssign. */
                source_offset = (source_offset + 3L); /* Вычислить, затем записать. */
                /* Python: строка 382; If. */
                if (flip_x) {
                    /* Python: строка 383; AugAssign. */
                    code = (code ^ 16384L); /* Вычислить, затем записать. */
                }
                /* Python: строка 384; If. */
                if (flip_y) {
                    /* Python: строка 385; AugAssign. */
                    code = (code ^ 32768L); /* Вычислить, затем записать. */
                }
                /* Python: строка 386. */
                pybuf_error=PyView_Index(pybuf_field_1,layer,&pybuf_selected_0);
                if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,387);
                pybuf_values[0]=code;
                pybuf_values[1]=attribute;
                pybuf_error=Tilemaps_DrawStrip_pack_1(pybuf_selected_0,output,pybuf_values);
                if(pybuf_error) return PyBuf_Fail(pybuf_fault,pybuf_error,386);
                /* Python: строка 388; AugAssign. */
                output = (output + output_step); /* Вычислить, затем записать. */
            }
        }
        /* Python: строка 389; AugAssign. */
        base_di = (base_di + 1536L); /* Вычислить, затем записать. */
    }
    return 1;
}
