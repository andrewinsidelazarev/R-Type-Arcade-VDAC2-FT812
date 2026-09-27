/* Generated from active Python AST/DrawPlanIR. Do not edit. */
#include "rtype_python_draw_state.h"

static const uint8_t rtype_python_draw_state_class_masks[
        RTYPE_PYTHON_DRAW_STATE_CLASS_COUNT][RTYPE_PYTHON_DRAW_VM_CLASS_BIT_BYTES] = {
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x01u, 0x00u, 0x00u, 0x00u },
    { 0x02u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x04u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x08u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x10u, 0x00u, 0x00u, 0x00u },
    { 0x20u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x40u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x10u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x80u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x01u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x02u, 0x00u, 0x00u },
    { 0x00u, 0x04u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x08u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x10u, 0x00u, 0x00u },
    { 0x00u, 0x10u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x20u, 0x00u, 0x00u },
    { 0x00u, 0x40u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x80u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x01u, 0x00u },
    { 0x00u, 0x00u, 0x02u, 0x00u },
    { 0x00u, 0x00u, 0x04u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x08u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x10u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x20u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x40u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x80u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x01u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x02u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u },
    { 0x00u, 0x00u, 0x00u, 0x00u }
};

static const uint8_t rtype_python_draw_state_site_fields[
        RTYPE_PYTHON_DRAW_STATE_MUTATION_SITE_COUNT] = { 11u, 11u, 12u, 12u, 11u, 12u, 7u, 2u, 8u, 11u, 12u, 7u, 2u, 8u, 2u, 7u, 12u, 11u, 11u, 8u, 9u, 9u, 9u, 11u, 2u, 11u, 2u, 11u, 9u, 12u, 11u, 2u, 12u, 9u, 11u, 2u, 9u, 11u, 2u, 9u, 9u, 11u, 2u, 11u, 2u, 11u, 11u, 2u, 9u, 9u, 3u, 11u, 2u, 8u, 8u, 11u, 2u, 11u, 2u, 11u, 12u, 2u, 11u, 9u, 7u, 9u, 2u, 7u, 9u, 11u, 12u, 2u, 11u, 2u, 2u, 12u, 11u, 2u, 12u, 9u, 9u, 11u, 2u, 9u, 11u, 11u, 2u, 9u, 9u, 11u, 2u, 12u, 9u, 9u, 11u, 12u, 2u, 9u, 11u, 2u, 9u, 10u, 2u, 10u, 11u, 2u, 2u, 11u, 12u, 2u, 8u, 11u, 12u, 2u, 9u, 8u, 11u, 2u, 11u, 2u, 7u, 9u, 9u, 9u, 11u, 11u, 12u, 11u, 2u, 11u, 12u, 11u, 11u, 2u, 11u, 12u, 11u, 2u, 11u, 2u, 11u, 2u, 9u, 11u, 12u, 11u, 2u, 11u, 9u, 2u, 2u, 2u, 11u, 12u, 2u, 11u, 12u, 2u, 11u, 12u, 11u, 2u, 11u, 12u, 11u, 2u, 11u, 11u, 11u, 9u, 11u, 12u, 9u, 11u, 2u, 11u, 2u, 9u, 9u, 9u, 9u, 9u, 2u, 11u, 12u, 2u, 11u, 12u, 2u, 9u, 2u, 9u, 2u, 9u, 9u, 9u, 11u, 12u, 2u, 9u, 11u, 12u, 2u, 9u, 1u, 9u, 11u, 12u, 7u, 9u, 7u, 9u, 9u, 2u, 2u, 11u, 12u, 2u, 12u, 12u, 2u, 9u, 11u, 2u, 9u, 9u, 9u, 9u, 11u, 12u, 11u, 2u, 2u, 9u, 2u, 2u, 9u, 11u, 2u, 9u, 12u, 2u, 9u, 2u, 9u, 2u, 9u, 2u, 9u, 2u, 11u, 12u, 7u, 11u, 2u, 2u, 2u, 9u, 9u, 9u, 9u, 9u, 9u, 2u, 9u, 11u, 9u, 11u, 2u, 9u, 2u, 2u, 9u, 2u, 11u, 2u, 9u, 7u, 9u, 7u, 11u, 2u, 11u, 4u, 5u, 6u, 11u, 12u, 7u, 7u, 11u, 2u, 2u, 5u, 6u, 4u, 9u, 11u, 12u, 2u, 12u, 11u, 9u, 11u, 9u, 9u, 11u, 9u, 11u, 9u, 11u, 9u, 9u, 9u, 9u, 9u, 11u, 7u, 9u, 11u, 2u, 11u, 2u, 2u, 2u, 2u, 7u, 9u, 9u, 12u, 11u, 2u, 11u, 2u, 9u, 12u, 11u, 2u, 9u, 9u, 8u, 11u, 2u, 7u, 9u, 2u, 9u, 2u, 11u, 7u, 9u, 8u, 9u, 9u, 11u, 7u, 9u, 11u, 2u, 2u, 9u, 11u, 12u, 9u, 9u, 11u, 9u, 11u };
static const uint32_t rtype_python_draw_state_site_hashes[
        RTYPE_PYTHON_DRAW_STATE_MUTATION_SITE_COUNT] = {
    0xB4137B1DUL,
    0xF283EE2DUL,
    0xDC8ECE23UL,
    0x207DA9D2UL,
    0xC6DA117EUL,
    0x3B897C65UL,
    0x8B27E812UL,
    0x681FB2EEUL,
    0x30BD6BB2UL,
    0xA98F9E8AUL,
    0x08C11DA8UL,
    0x826CF8FBUL,
    0x139D6CAAUL,
    0x683745DBUL,
    0xAE79101EUL,
    0xD2B3726FUL,
    0xA0BDC57BUL,
    0x73E14E9AUL,
    0xCF527924UL,
    0x0C43B8CCUL,
    0x09116067UL,
    0x54706EADUL,
    0x48CA7B5FUL,
    0x8A0BDCDCUL,
    0x7267D608UL,
    0x49F2E46EUL,
    0x4998DB94UL,
    0x453584F4UL,
    0xBF5E93A8UL,
    0x1E19B62AUL,
    0xF5AB167DUL,
    0x0DB5113CUL,
    0x7CF55278UL,
    0x6AC36E07UL,
    0xD8A63313UL,
    0x6A67762DUL,
    0x8157E090UL,
    0x02319616UL,
    0x7353D920UL,
    0xA03D7431UL,
    0xD21F389DUL,
    0x80B9A97AUL,
    0x1B804D0DUL,
    0xC3446CAEUL,
    0x7619F47EUL,
    0xB05D67E4UL,
    0x4D808BF2UL,
    0x6F9B4F09UL,
    0x5D643585UL,
    0xE64140B9UL,
    0x0B8400A6UL,
    0x76A9BE74UL,
    0x0918FF76UL,
    0x658D9F42UL,
    0x8C52AA71UL,
    0x2A902C02UL,
    0xC82C83A7UL,
    0xE840A4A3UL,
    0x0F8854D7UL,
    0xAA9E29E4UL,
    0x8726CAC1UL,
    0xB74BD691UL,
    0xE081D467UL,
    0x4DE39613UL,
    0xD9A146CFUL,
    0x9D84E230UL,
    0x62329A59UL,
    0x458E304FUL,
    0x4DE6732BUL,
    0x569A6F59UL,
    0x6FE4A08DUL,
    0x6802D5EBUL,
    0xAFB8E177UL,
    0xD0234FACUL,
    0x5F96E2B7UL,
    0x063D2C61UL,
    0x9FBEAA84UL,
    0x6986C44FUL,
    0x3C7591C0UL,
    0x9E4FC149UL,
    0x18A0B683UL,
    0xD1CE4CF3UL,
    0x00260098UL,
    0xE6208446UL,
    0xD2EBDBBBUL,
    0x9B293FC4UL,
    0x42CD8025UL,
    0x94DAD296UL,
    0xF597E205UL,
    0xCFB91234UL,
    0xD7F6C850UL,
    0x28E56CFEUL,
    0x835FFE76UL,
    0x74EAFAEAUL,
    0x0A12C23EUL,
    0xBF43F410UL,
    0xFA14443BUL,
    0x0A7FBB5FUL,
    0x97702D33UL,
    0x42E6B46BUL,
    0xAC5F7DB2UL,
    0x256B4B95UL,
    0xCDD31049UL,
    0x2E82F856UL,
    0xAE33C805UL,
    0x8EA15E97UL,
    0x457EA364UL,
    0x6090B180UL,
    0x48EE935BUL,
    0x353EEF13UL,
    0xF15047BDUL,
    0xDCC4487BUL,
    0xA63B72A7UL,
    0xD20A9A4DUL,
    0x1240E0D2UL,
    0xE3756419UL,
    0xBFD7AE64UL,
    0xEE34D543UL,
    0x8AB73726UL,
    0x78279FD5UL,
    0x9B55CF4BUL,
    0x667625D5UL,
    0xC42088A9UL,
    0x7ADED24FUL,
    0x7EDC5C03UL,
    0x00D949E6UL,
    0x6448D8BEUL,
    0x4FEBA2A8UL,
    0x910C20FCUL,
    0x3B55DC81UL,
    0xEBBE4218UL,
    0x9B059F2AUL,
    0x5D7C9B88UL,
    0x4DC800F7UL,
    0x56C0AA4BUL,
    0x205FFD5CUL,
    0x7CDE49D9UL,
    0x3376001AUL,
    0x0CDD82A2UL,
    0x71D4938AUL,
    0x9030BC3AUL,
    0x84F4F2B1UL,
    0x0601B7C1UL,
    0xBB1EA081UL,
    0x9E06582FUL,
    0xDA20FDA9UL,
    0x52F490EBUL,
    0x65893906UL,
    0xC0EF59F0UL,
    0x4CF3481DUL,
    0x42C9F3BDUL,
    0xADCEB064UL,
    0x2765032DUL,
    0x2FCB682FUL,
    0x3C59D75BUL,
    0xAE1085EEUL,
    0x65A26C9CUL,
    0x14BBD68AUL,
    0x28CE47BFUL,
    0x4D28C937UL,
    0x8C5E25D8UL,
    0x1928E983UL,
    0x1EBA96BBUL,
    0xE66778BEUL,
    0x89077A14UL,
    0x981E8522UL,
    0x6F565ECEUL,
    0x05A3EE39UL,
    0x70463537UL,
    0x637B4E72UL,
    0x64049CC4UL,
    0xF41D8C33UL,
    0x9A14E268UL,
    0xE76F655AUL,
    0x2A25065CUL,
    0x57BF9E8CUL,
    0x755AF4F1UL,
    0xC904FE51UL,
    0x56CF143FUL,
    0x120C3056UL,
    0x36C29085UL,
    0xDEA1E913UL,
    0x63BACF77UL,
    0x9EA24904UL,
    0x75B79495UL,
    0xB7AAC7C3UL,
    0xFCA217F4UL,
    0x2E5C2E96UL,
    0x677982B6UL,
    0x08433B5FUL,
    0x3253F964UL,
    0x298951D8UL,
    0x70274C0FUL,
    0x18F979ACUL,
    0xF492C6F9UL,
    0x56562239UL,
    0x1660FD10UL,
    0xE6C89415UL,
    0xF5DC12AAUL,
    0xCAC07A95UL,
    0xB7EBB031UL,
    0xD301905DUL,
    0xEB9017D1UL,
    0xDB00C4E4UL,
    0x58D58F48UL,
    0x3F1A7203UL,
    0x68B01BEEUL,
    0xE97312C8UL,
    0x998AA0CCUL,
    0xA89E5A13UL,
    0x7578E9D8UL,
    0xC1E2B3F8UL,
    0x90BAA1ABUL,
    0x5401E808UL,
    0xAB55ABE9UL,
    0x264FF078UL,
    0x1A6FDE0BUL,
    0xC0A1A74DUL,
    0x1F2938B9UL,
    0xF3E78F49UL,
    0x1F25C159UL,
    0x01EBCFE8UL,
    0x54870130UL,
    0x5C688A51UL,
    0x2C5A4A17UL,
    0x460B166DUL,
    0x5B9E8B5EUL,
    0x48C3693CUL,
    0x86376988UL,
    0x3906E578UL,
    0xD0BEBC9FUL,
    0xB58B9C7DUL,
    0x26733EACUL,
    0xCEB82FC1UL,
    0x839F6581UL,
    0x24EAD03DUL,
    0xA1ED6DC3UL,
    0xBEAEB925UL,
    0xECFE58CFUL,
    0x48368663UL,
    0x08CDC2DCUL,
    0x0021C3ABUL,
    0xABDA0DD6UL,
    0xCCBBFFE7UL,
    0x4F1F4A6AUL,
    0xE07AFAA4UL,
    0xCBF87440UL,
    0x3C4020FEUL,
    0x9B1231CEUL,
    0x53A1A240UL,
    0x761030EDUL,
    0x600A8AFBUL,
    0xD549E6A5UL,
    0xD924F2E7UL,
    0x82645E98UL,
    0x4CF8E182UL,
    0x5BC56DDEUL,
    0xA36F715EUL,
    0x76A855ABUL,
    0xDC913D84UL,
    0x054AE23FUL,
    0xFE24CCD9UL,
    0x49398799UL,
    0xC9A861BAUL,
    0xA1DF7F1DUL,
    0x38160DFBUL,
    0xFC5B46A5UL,
    0xD1CB5D84UL,
    0xEE3C330DUL,
    0x9FE68462UL,
    0xA9BCB9CBUL,
    0xFB6B51D3UL,
    0x2562C0CAUL,
    0x2F4EC0CEUL,
    0xF7DC660DUL,
    0x721DD393UL,
    0xD5E756D9UL,
    0xA6EC0AADUL,
    0xF5392615UL,
    0x90329442UL,
    0x377C947DUL,
    0x8E4C1E27UL,
    0x3399545CUL,
    0xA6F3B4FBUL,
    0x30660670UL,
    0xEDC2DC44UL,
    0x86CAEA07UL,
    0x26831AC1UL,
    0xA4386C28UL,
    0x2C1CF5ADUL,
    0xDCC7555EUL,
    0x95DDD89AUL,
    0x00B749FCUL,
    0xABE687EEUL,
    0xF23FD8C6UL,
    0x48E17A32UL,
    0xBD06707CUL,
    0x4D123B27UL,
    0xD26E8DBCUL,
    0xFB40D963UL,
    0x4773DD59UL,
    0x1244E518UL,
    0x20F08F63UL,
    0xD89F08B7UL,
    0x7EF3621CUL,
    0x31D79AF8UL,
    0x9B804478UL,
    0x63C92FDEUL,
    0x873F6AB1UL,
    0x63516EFAUL,
    0x93236775UL,
    0xB3BFC1FEUL,
    0x64E786DFUL,
    0x3FF939C6UL,
    0x28B39A15UL,
    0x06B491C7UL,
    0xB48E39A5UL,
    0xBC79AFB2UL,
    0x1879B11AUL,
    0x164615F6UL,
    0x97AFFED6UL,
    0x539AC0BDUL,
    0xEABB5ED3UL,
    0x012076B8UL,
    0xEA34C560UL,
    0x77E06D73UL,
    0x6A935D6FUL,
    0x8948FA47UL,
    0xCE8F3A8AUL,
    0x5F8A1A62UL,
    0xFBDDD754UL,
    0x77EA1A3EUL,
    0xE99924C8UL,
    0xC1CBCE61UL,
    0xFF317031UL,
    0x08F39D21UL,
    0x7AA22F8EUL,
    0x7C23F99BUL,
    0x09944C59UL,
    0x69CF40DEUL,
    0x66710BE8UL,
    0x51BA7332UL,
    0x855DCB9FUL,
    0xFBA63C52UL,
    0x595223C9UL,
    0xF90AB7FAUL,
    0xFF046DE0UL,
    0x5472C5CBUL,
    0xA5BD59C8UL,
    0xA7F48DD2UL,
    0x6E73F6B2UL,
    0x2562DF99UL,
    0xA3A6FEB7UL,
    0x5F737D57UL,
    0x0F1FFF26UL,
    0xC0A562A6UL,
    0xE407FBC2UL,
    0x043519D1UL,
    0x879FDAFCUL,
    0x705102C9UL,
    0xBD6EC228UL,
    0xA7BF59C6UL,
    0xE61D2F27UL,
    0xD8E5DD33UL,
    0xE982F2F3UL,
    0xFCD86FF6UL,
    0xE7294D6CUL,
    0x565C4130UL
};

static uint8_t rtype_python_draw_state_valid_slot(uint8_t slot)
{
    return (uint8_t)(slot >= RTYPE_PYTHON_DRAW_STATE_RESERVED_SENTINELS &&
                     slot < RTYPE_PYTHON_DRAW_STATE_SLOT_COUNT);
}

static uint8_t rtype_python_draw_state_valid_values(
        const rtype_python_draw_state_values *values, uint16_t mask)
{
    if (values == 0) return 0u;
    if ((mask & 0x0002u) != 0u &&
            ((int32_t)values->field_body_kind < 0L ||
             (int32_t)values->field_body_kind > 2L)) return 0u;
    if ((mask & 0x0008u) != 0u &&
            ((int32_t)values->field_effect < 0L ||
             (int32_t)values->field_effect > 1L)) return 0u;
    if ((mask & 0x0100u) != 0u &&
            ((int32_t)values->field_render_ready < 0L ||
             (int32_t)values->field_render_ready > 1L)) return 0u;
    if ((mask & 0x0200u) != 0u &&
            ((int32_t)values->field_state < 0L ||
             (int32_t)values->field_state > 1L)) return 0u;
    if ((mask & 0x0400u) != 0u &&
            ((int32_t)values->field_visible < 0L ||
             (int32_t)values->field_visible > 1L)) return 0u;
    return 1u;
}

static void rtype_python_draw_state_zero_slot(rtype_python_draw_state_slot_state *slot_state)
{
    slot_state->values.field_active_palette = 0;
    slot_state->values.field_body_kind = 0;
    slot_state->values.field_descriptor = 0;
    slot_state->values.field_effect = 0;
    slot_state->values.field_overlay_descriptor = 0;
    slot_state->values.field_overlay_x = 0;
    slot_state->values.field_overlay_y = 0;
    slot_state->values.field_palette = 0;
    slot_state->values.field_render_ready = 0;
    slot_state->values.field_state = 0;
    slot_state->values.field_visible = 0;
    slot_state->values.field_x = 0;
    slot_state->values.field_y = 0;
    slot_state->concrete_class = RTYPE_PYTHON_DRAW_STATE_CLASS_NONE;
    slot_state->reserved_zero = 0u;
}

void rtype_python_draw_state_reset(rtype_python_draw_state_state *state)
{
    uint8_t slot;
    if (state == 0) return;
    for (slot = 0u; slot < RTYPE_PYTHON_DRAW_STATE_SLOT_COUNT; ++slot)
        rtype_python_draw_state_zero_slot(&state->slots[slot]);
}

rtype_python_draw_state_status rtype_python_draw_state_clear(rtype_python_draw_state_state *state, uint8_t slot)
{
    if (state == 0) return RTYPE_PYTHON_DRAW_STATE_NULL;
    if (!rtype_python_draw_state_valid_slot(slot)) return RTYPE_PYTHON_DRAW_STATE_INVALID_SLOT;
    if (state->slots[slot].concrete_class == RTYPE_PYTHON_DRAW_STATE_CLASS_NONE)
        return RTYPE_PYTHON_DRAW_STATE_UNBOUND_SLOT;
    rtype_python_draw_state_zero_slot(&state->slots[slot]);
    return RTYPE_PYTHON_DRAW_STATE_OK;
}

static rtype_python_draw_state_status rtype_python_draw_state_write(
        rtype_python_draw_state_state *state, uint8_t slot, uint8_t concrete_class,
        const rtype_python_draw_state_values *values, uint8_t require_bound)
{
    if (state == 0 || values == 0) return RTYPE_PYTHON_DRAW_STATE_NULL;
    if (!rtype_python_draw_state_valid_slot(slot)) return RTYPE_PYTHON_DRAW_STATE_INVALID_SLOT;
    if (concrete_class >= RTYPE_PYTHON_DRAW_STATE_CLASS_COUNT)
        return RTYPE_PYTHON_DRAW_STATE_INVALID_CLASS;
    if (require_bound != 0u &&
            state->slots[slot].concrete_class == RTYPE_PYTHON_DRAW_STATE_CLASS_NONE)
        return RTYPE_PYTHON_DRAW_STATE_UNBOUND_SLOT;
    if (require_bound == 0u &&
            state->slots[slot].concrete_class != RTYPE_PYTHON_DRAW_STATE_CLASS_NONE)
        return RTYPE_PYTHON_DRAW_STATE_ALREADY_BOUND;
    if (!rtype_python_draw_state_valid_values(values, 0x1FFFu))
        return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
    state->slots[slot].values = *values;
    state->slots[slot].reserved_zero = 0u;
    state->slots[slot].concrete_class = concrete_class;
    return RTYPE_PYTHON_DRAW_STATE_OK;
}

rtype_python_draw_state_status rtype_python_draw_state_bind(
        rtype_python_draw_state_state *state, uint8_t slot, uint8_t concrete_class,
        const rtype_python_draw_state_values *values)
{
    return rtype_python_draw_state_write(state, slot, concrete_class, values, 0u);
}

rtype_python_draw_state_status rtype_python_draw_state_replace_same_slot(
        rtype_python_draw_state_state *state, uint8_t slot, uint8_t concrete_class,
        const rtype_python_draw_state_values *values)
{
    return rtype_python_draw_state_write(state, slot, concrete_class, values, 1u);
}

rtype_python_draw_state_status rtype_python_draw_state_patch(
        rtype_python_draw_state_state *state, uint8_t slot, uint16_t field_mask,
        const rtype_python_draw_state_values *values)
{
    if (state == 0 || values == 0) return RTYPE_PYTHON_DRAW_STATE_NULL;
    if (!rtype_python_draw_state_valid_slot(slot)) return RTYPE_PYTHON_DRAW_STATE_INVALID_SLOT;
    if (state->slots[slot].concrete_class == RTYPE_PYTHON_DRAW_STATE_CLASS_NONE)
        return RTYPE_PYTHON_DRAW_STATE_UNBOUND_SLOT;
    if ((field_mask & (uint16_t)~0x1FFFu) != 0u)
        return RTYPE_PYTHON_DRAW_STATE_INVALID_PATCH_MASK;
    if (!rtype_python_draw_state_valid_values(values, field_mask))
        return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
    if ((field_mask & 0x0001u) != 0u) state->slots[slot].values.field_active_palette = values->field_active_palette;
    if ((field_mask & 0x0002u) != 0u) state->slots[slot].values.field_body_kind = values->field_body_kind;
    if ((field_mask & 0x0004u) != 0u) state->slots[slot].values.field_descriptor = values->field_descriptor;
    if ((field_mask & 0x0008u) != 0u) state->slots[slot].values.field_effect = values->field_effect;
    if ((field_mask & 0x0010u) != 0u) state->slots[slot].values.field_overlay_descriptor = values->field_overlay_descriptor;
    if ((field_mask & 0x0020u) != 0u) state->slots[slot].values.field_overlay_x = values->field_overlay_x;
    if ((field_mask & 0x0040u) != 0u) state->slots[slot].values.field_overlay_y = values->field_overlay_y;
    if ((field_mask & 0x0080u) != 0u) state->slots[slot].values.field_palette = values->field_palette;
    if ((field_mask & 0x0100u) != 0u) state->slots[slot].values.field_render_ready = values->field_render_ready;
    if ((field_mask & 0x0200u) != 0u) state->slots[slot].values.field_state = values->field_state;
    if ((field_mask & 0x0400u) != 0u) state->slots[slot].values.field_visible = values->field_visible;
    if ((field_mask & 0x0800u) != 0u) state->slots[slot].values.field_x = values->field_x;
    if ((field_mask & 0x1000u) != 0u) state->slots[slot].values.field_y = values->field_y;
    return RTYPE_PYTHON_DRAW_STATE_OK;
}

rtype_python_draw_state_status rtype_python_draw_state_set_field(
        rtype_python_draw_state_state *state, uint8_t slot, uint8_t field_id,
        int32_t value)
{
    if (state == 0) return RTYPE_PYTHON_DRAW_STATE_NULL;
    if (!rtype_python_draw_state_valid_slot(slot)) return RTYPE_PYTHON_DRAW_STATE_INVALID_SLOT;
    if (state->slots[slot].concrete_class == RTYPE_PYTHON_DRAW_STATE_CLASS_NONE)
        return RTYPE_PYTHON_DRAW_STATE_UNBOUND_SLOT;
    switch (field_id) {
    case 0u:
        if (value < 0L || value > 65535L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_active_palette = (uint16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 1u:
        if (value < 0L || value > 2L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_body_kind = (uint16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 2u:
        if (value < 0L || value > 65535L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_descriptor = (uint16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 3u:
        if (value < 0L || value > 1L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_effect = (uint16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 4u:
        if (value < 0L || value > 65535L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_overlay_descriptor = (uint16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 5u:
        if (value < -32768L || value > 32767L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_overlay_x = (int16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 6u:
        if (value < -32768L || value > 32767L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_overlay_y = (int16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 7u:
        if (value < 0L || value > 65535L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_palette = (uint16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 8u:
        if (value < 0L || value > 1L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_render_ready = (uint8_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 9u:
        if (value < 0L || value > 1L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_state = (uint16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 10u:
        if (value < 0L || value > 1L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_visible = (uint8_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 11u:
        if (value < -32768L || value > 32767L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_x = (int16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    case 12u:
        if (value < -32768L || value > 32767L)
            return RTYPE_PYTHON_DRAW_STATE_VALUE_RANGE;
        state->slots[slot].values.field_y = (int16_t)value;
        return RTYPE_PYTHON_DRAW_STATE_OK;
    default: return RTYPE_PYTHON_DRAW_STATE_INVALID_FIELD;
    }
}

rtype_python_draw_state_status rtype_python_draw_state_set_at_site(
        rtype_python_draw_state_state *state, uint8_t slot, uint16_t site_id,
        int32_t value)
{
    if (site_id >= RTYPE_PYTHON_DRAW_STATE_MUTATION_SITE_COUNT)
        return RTYPE_PYTHON_DRAW_STATE_INVALID_SITE;
    return rtype_python_draw_state_set_field(
        state, slot, rtype_python_draw_state_site_fields[site_id], value);
}

uint32_t rtype_python_draw_state_mutation_site_hash32(uint16_t site_id)
{
    if (site_id >= RTYPE_PYTHON_DRAW_STATE_MUTATION_SITE_COUNT) return 0UL;
    return rtype_python_draw_state_site_hashes[site_id];
}

uint8_t rtype_python_draw_state_class_of(
        const rtype_python_draw_state_state *state, uint8_t slot)
{
    if (state == 0 || !rtype_python_draw_state_valid_slot(slot))
        return RTYPE_PYTHON_DRAW_STATE_CLASS_NONE;
    return state->slots[slot].concrete_class;
}

uint8_t rtype_python_draw_state_load_object(
        void *context, uint16_t object_index,
        rtype_python_draw_vm_object_view *object_out)
{
    const rtype_python_draw_state_provider_context *provider =
        (const rtype_python_draw_state_provider_context *)context;
    const rtype_python_draw_state_slot_state *slot_state;
    uint8_t slot;
    uint8_t index;
    if (provider == 0 || provider->state == 0 ||
            provider->order == 0 || object_out == 0 ||
            object_index > 0xFFu) return 0u;
    slot = rtype_python_render_order_slot_at(
        provider->order, (uint8_t)object_index);
    if (!rtype_python_draw_state_valid_slot(slot)) return 0u;
    slot_state = &provider->state->slots[slot];
    if (slot_state->concrete_class >= RTYPE_PYTHON_DRAW_STATE_CLASS_COUNT) return 0u;
    for (index = 0u; index < RTYPE_PYTHON_DRAW_VM_CLASS_BIT_BYTES;
            ++index)
        object_out->class_bits[index] = rtype_python_draw_state_class_masks[
            slot_state->concrete_class][index];
    object_out->field_active_palette = slot_state->values.field_active_palette;
    object_out->field_body_kind = slot_state->values.field_body_kind;
    object_out->field_descriptor = slot_state->values.field_descriptor;
    object_out->field_effect = slot_state->values.field_effect;
    object_out->field_overlay_descriptor = slot_state->values.field_overlay_descriptor;
    object_out->field_overlay_x = slot_state->values.field_overlay_x;
    object_out->field_overlay_y = slot_state->values.field_overlay_y;
    object_out->field_palette = slot_state->values.field_palette;
    object_out->field_render_ready = slot_state->values.field_render_ready;
    object_out->field_state = slot_state->values.field_state;
    object_out->field_visible = slot_state->values.field_visible;
    object_out->field_x = slot_state->values.field_x;
    object_out->field_y = slot_state->values.field_y;
    return 1u;
}
