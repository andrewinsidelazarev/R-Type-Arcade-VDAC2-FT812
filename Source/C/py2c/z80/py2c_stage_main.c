/* Кадровый драйвер SPG транслированного Stage: порядок вызовов как в Game.update/render
 * для ландшафта (update, затем задний и передний слой). Логики игры здесь нет.
 * Ограничение демонстрационного профиля: в RAM_G загружены атласы участков 0–1,
 * поэтому при переходе на участок 2 состояние снимка восстанавливается заново. */
#include "py2c_stage.h"
#include "py2c_ft812.h"

#define PY2C_DEMO_SECTIONS 2

uint16_t py2c_frames;
uint8_t py2c_restarts;

void Py2c_Init(void) {
    py2c_init();
    py2c_frames = 0;
}

void Py2c_Frame(void) {
    Stage_update(PY2C_ROOT_STAGE);
    py2c_frame_begin();
    Stage_draw_back(PY2C_ROOT_STAGE, 0);
    Stage_draw_front(PY2C_ROOT_STAGE, 0);
    py2c_frame_end();
    ++py2c_frames;
    if (PY2C_ROOT_STAGE->section_index >= PY2C_DEMO_SECTIONS) {
        py2c_init();
        ++py2c_restarts;
    }
}

void py2c_code_end(void) {
}
