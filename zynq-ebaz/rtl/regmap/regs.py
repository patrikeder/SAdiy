"""Register map constants of the SAdiy PL sweep engine.

generated from regmap.toml by gen_regs.py, do not edit.
"""

ADDR_WIDTH = 12
MAP_VERSION = 0x00010000
ID_MAGIC = 0x53410001


def get_field(word, lsb, width):
    """Extract the field at bit lsb, width bits wide, from a 32-bit word."""
    return (word >> lsb) & ((1 << width) - 1)


def set_field(word, lsb, width, value):
    """Return word with the field at lsb / width replaced by value (value is masked)."""
    mask = ((1 << width) - 1) << lsb
    return (word & ~mask) | ((value << lsb) & mask)


# register offsets, field positions and reset values

ID = 0x000
ID_RESET = 0x53410001
ID_MAGIC_LSB = 0
ID_MAGIC_WIDTH = 32
ID_MAGIC_MASK = 0xFFFFFFFF

VERSION = 0x004
VERSION_RESET = 0x00010000
VERSION_VERSION_LSB = 0
VERSION_VERSION_WIDTH = 32
VERSION_VERSION_MASK = 0xFFFFFFFF

CTRL = 0x008
CTRL_RESET = 0x00000000
CTRL_START_LSB = 0
CTRL_START_WIDTH = 1
CTRL_START_MASK = 0x00000001
CTRL_ABORT_LSB = 1
CTRL_ABORT_WIDTH = 1
CTRL_ABORT_MASK = 0x00000002
CTRL_SOFT_RESET_LSB = 2
CTRL_SOFT_RESET_WIDTH = 1
CTRL_SOFT_RESET_MASK = 0x00000004
CTRL_IRQ_EN_LSB = 3
CTRL_IRQ_EN_WIDTH = 1
CTRL_IRQ_EN_MASK = 0x00000008
CTRL_PIN_OWNER_LSB = 4
CTRL_PIN_OWNER_WIDTH = 1
CTRL_PIN_OWNER_MASK = 0x00000010
CTRL_STOP_ON_ERR_LSB = 5
CTRL_STOP_ON_ERR_WIDTH = 1
CTRL_STOP_ON_ERR_MASK = 0x00000020
CTRL_IRQ_ACK_LSB = 6
CTRL_IRQ_ACK_WIDTH = 1
CTRL_IRQ_ACK_MASK = 0x00000040

STATUS = 0x00C
STATUS_RESET = 0x00000000
STATUS_BUSY_LSB = 0
STATUS_BUSY_WIDTH = 1
STATUS_BUSY_MASK = 0x00000001
STATUS_DONE_LSB = 1
STATUS_DONE_WIDTH = 1
STATUS_DONE_MASK = 0x00000002
STATUS_ERR_LOCK_LSB = 2
STATUS_ERR_LOCK_WIDTH = 1
STATUS_ERR_LOCK_MASK = 0x00000004
STATUS_ABORTED_LSB = 3
STATUS_ABORTED_WIDTH = 1
STATUS_ABORTED_MASK = 0x00000008
STATUS_LD_NOW_LSB = 4
STATUS_LD_NOW_WIDTH = 1
STATUS_LD_NOW_MASK = 0x00000010
STATUS_WAIT_SAMPLE_LSB = 5
STATUS_WAIT_SAMPLE_WIDTH = 1
STATUS_WAIT_SAMPLE_MASK = 0x00000020
STATUS_ERR_TABLE_LSB = 6
STATUS_ERR_TABLE_WIDTH = 1
STATUS_ERR_TABLE_MASK = 0x00000040
STATUS_PIN_OWNER_ACT_LSB = 7
STATUS_PIN_OWNER_ACT_WIDTH = 1
STATUS_PIN_OWNER_ACT_MASK = 0x00000080
STATUS_STATE_LSB = 8
STATUS_STATE_WIDTH = 4
STATUS_STATE_MASK = 0x00000F00

N_ENTRIES = 0x010
N_ENTRIES_RESET = 0x00000000
N_ENTRIES_N_LSB = 0
N_ENTRIES_N_WIDTH = 16
N_ENTRIES_N_MASK = 0x0000FFFF

N_AVG = 0x014
N_AVG_RESET = 0x00000001
N_AVG_N_LSB = 0
N_AVG_N_WIDTH = 12
N_AVG_N_MASK = 0x00000FFF

SPI_DIV = 0x018
SPI_DIV_RESET = 0x00000005
SPI_DIV_DIV_LSB = 0
SPI_DIV_DIV_WIDTH = 8
SPI_DIV_DIV_MASK = 0x000000FF

T_ATT_GAP_CYC = 0x01C
T_ATT_GAP_CYC_RESET = 0x00000064
T_ATT_GAP_CYC_CYCLES_LSB = 0
T_ATT_GAP_CYC_CYCLES_WIDTH = 16
T_ATT_GAP_CYC_CYCLES_MASK = 0x0000FFFF

T_MIN_US = 0x020
T_MIN_US_RESET = 0x000000C8
T_MIN_US_US_LSB = 0
T_MIN_US_US_WIDTH = 20
T_MIN_US_US_MASK = 0x000FFFFF

T_LOCK_STABLE_US = 0x024
T_LOCK_STABLE_US_RESET = 0x00000032
T_LOCK_STABLE_US_US_LSB = 0
T_LOCK_STABLE_US_US_WIDTH = 20
T_LOCK_STABLE_US_US_MASK = 0x000FFFFF

T_LOCK_TIMEOUT_US = 0x028
T_LOCK_TIMEOUT_US_RESET = 0x00002710
T_LOCK_TIMEOUT_US_US_LSB = 0
T_LOCK_TIMEOUT_US_US_WIDTH = 20
T_LOCK_TIMEOUT_US_US_MASK = 0x000FFFFF

T_SETTLE_US = 0x02C
T_SETTLE_US_RESET = 0x000001F4
T_SETTLE_US_US_LSB = 0
T_SETTLE_US_US_WIDTH = 20
T_SETTLE_US_US_MASK = 0x000FFFFF

PE4302 = 0x030
PE4302_RESET = 0x0000013F
PE4302_MANUAL_LSB = 0
PE4302_MANUAL_WIDTH = 6
PE4302_MANUAL_MASK = 0x0000003F
PE4302_ACTIVE_HIGH_LSB = 8
PE4302_ACTIVE_HIGH_WIDTH = 1
PE4302_ACTIVE_HIGH_MASK = 0x00000100

PIN_STATE = 0x034
PIN_STATE_RESET = 0x00000000
PIN_STATE_PE_IN_LSB = 0
PIN_STATE_PE_IN_WIDTH = 6
PIN_STATE_PE_IN_MASK = 0x0000003F
PIN_STATE_LD_LSB = 8
PIN_STATE_LD_WIDTH = 1
PIN_STATE_LD_MASK = 0x00000100
PIN_STATE_LE_LSB = 9
PIN_STATE_LE_WIDTH = 1
PIN_STATE_LE_MASK = 0x00000200
PIN_STATE_CLK_LSB = 10
PIN_STATE_CLK_WIDTH = 1
PIN_STATE_CLK_MASK = 0x00000400
PIN_STATE_DAT_LSB = 11
PIN_STATE_DAT_WIDTH = 1
PIN_STATE_DAT_MASK = 0x00000800
PIN_STATE_PE_OUT_LSB = 16
PIN_STATE_PE_OUT_WIDTH = 6
PIN_STATE_PE_OUT_MASK = 0x003F0000
PIN_STATE_PE_T_LSB = 24
PIN_STATE_PE_T_WIDTH = 6
PIN_STATE_PE_T_MASK = 0x3F000000

DET_CFG = 0x038
DET_CFG_RESET = 0x00000000
DET_CFG_SRC_LSB = 0
DET_CFG_SRC_WIDTH = 2
DET_CFG_SRC_MASK = 0x00000003

DET_TEST = 0x03C
DET_TEST_RESET = 0x00000000
DET_TEST_BASE_LSB = 0
DET_TEST_BASE_WIDTH = 16
DET_TEST_BASE_MASK = 0x0000FFFF

DET_PUSH = 0x040
DET_PUSH_RESET = 0x00000000
DET_PUSH_SAMPLE_LSB = 0
DET_PUSH_SAMPLE_WIDTH = 16
DET_PUSH_SAMPLE_MASK = 0x0000FFFF

FIRST_ERR_INDEX = 0x044
FIRST_ERR_INDEX_RESET = 0x00000000
FIRST_ERR_INDEX_INDEX_LSB = 0
FIRST_ERR_INDEX_INDEX_WIDTH = 16
FIRST_ERR_INDEX_INDEX_MASK = 0x0000FFFF

POINT_COUNT = 0x048
POINT_COUNT_RESET = 0x00000000
POINT_COUNT_COUNT_LSB = 0
POINT_COUNT_COUNT_WIDTH = 16
POINT_COUNT_COUNT_MASK = 0x0000FFFF

SWEEP_COUNT = 0x04C
SWEEP_COUNT_RESET = 0x00000000
SWEEP_COUNT_COUNT_LSB = 0
SWEEP_COUNT_COUNT_WIDTH = 32
SWEEP_COUNT_COUNT_MASK = 0xFFFFFFFF

ENTRY_INDEX = 0x050
ENTRY_INDEX_RESET = 0x00000000
ENTRY_INDEX_INDEX_LSB = 0
ENTRY_INDEX_INDEX_WIDTH = 16
ENTRY_INDEX_INDEX_MASK = 0x0000FFFF

TABLE_ADDR = 0x060
TABLE_ADDR_RESET = 0x00000000
TABLE_ADDR_INDEX_LSB = 0
TABLE_ADDR_INDEX_WIDTH = 16
TABLE_ADDR_INDEX_MASK = 0x0000FFFF

TABLE_W0 = 0x064
TABLE_W0_RESET = 0x00000000
TABLE_W0_WORD_LSB = 0
TABLE_W0_WORD_WIDTH = 32
TABLE_W0_WORD_MASK = 0xFFFFFFFF

TABLE_W1 = 0x068
TABLE_W1_RESET = 0x00000000
TABLE_W1_ATT_LSB = 0
TABLE_W1_ATT_WIDTH = 6
TABLE_W1_ATT_MASK = 0x0000003F
TABLE_W1_SPI_EN_LSB = 8
TABLE_W1_SPI_EN_WIDTH = 1
TABLE_W1_SPI_EN_MASK = 0x00000100
TABLE_W1_ATT_EN_LSB = 9
TABLE_W1_ATT_EN_WIDTH = 1
TABLE_W1_ATT_EN_MASK = 0x00000200
TABLE_W1_MEASURE_LSB = 10
TABLE_W1_MEASURE_WIDTH = 1
TABLE_W1_MEASURE_MASK = 0x00000400
TABLE_W1_SKIP_LOCK_LSB = 11
TABLE_W1_SKIP_LOCK_WIDTH = 1
TABLE_W1_SKIP_LOCK_MASK = 0x00000800

RESULT_ADDR = 0x070
RESULT_ADDR_RESET = 0x00000000
RESULT_ADDR_INDEX_LSB = 0
RESULT_ADDR_INDEX_WIDTH = 16
RESULT_ADDR_INDEX_MASK = 0x0000FFFF

RESULT_DATA = 0x074
RESULT_DATA_RESET = 0x00000000
RESULT_DATA_SUM_LSB = 0
RESULT_DATA_SUM_WIDTH = 28
RESULT_DATA_SUM_MASK = 0x0FFFFFFF
RESULT_DATA_UNLOCKED_LSB = 31
RESULT_DATA_UNLOCKED_WIDTH = 1
RESULT_DATA_UNLOCKED_MASK = 0x80000000

CAPS = 0x078
CAPS_RESET = 0x00000000
CAPS_TABLE_AW_LSB = 0
CAPS_TABLE_AW_WIDTH = 8
CAPS_TABLE_AW_MASK = 0x000000FF
CAPS_RESULT_AW_LSB = 8
CAPS_RESULT_AW_WIDTH = 8
CAPS_RESULT_AW_MASK = 0x0000FF00
CAPS_CLK_MHZ_LSB = 16
CAPS_CLK_MHZ_WIDTH = 16
CAPS_CLK_MHZ_MASK = 0xFFFF0000


REGISTERS = {
    "ID": {
        "offset": 0x000,
        "ext": False,
        "fields": {
            "magic": {"lsb": 0, "width": 32, "access": "const", "reset": 0x53410001},
        },
    },
    "VERSION": {
        "offset": 0x004,
        "ext": False,
        "fields": {
            "version": {"lsb": 0, "width": 32, "access": "const", "reset": 0x00010000},
        },
    },
    "CTRL": {
        "offset": 0x008,
        "ext": False,
        "fields": {
            "start": {"lsb": 0, "width": 1, "access": "w1p", "reset": 0x00000000},
            "abort": {"lsb": 1, "width": 1, "access": "w1p", "reset": 0x00000000},
            "soft_reset": {"lsb": 2, "width": 1, "access": "w1p", "reset": 0x00000000},
            "irq_en": {"lsb": 3, "width": 1, "access": "rw", "reset": 0x00000000},
            "pin_owner": {"lsb": 4, "width": 1, "access": "rw", "reset": 0x00000000},
            "stop_on_err": {"lsb": 5, "width": 1, "access": "rw", "reset": 0x00000000},
            "irq_ack": {"lsb": 6, "width": 1, "access": "w1p", "reset": 0x00000000},
        },
    },
    "STATUS": {
        "offset": 0x00C,
        "ext": False,
        "fields": {
            "busy": {"lsb": 0, "width": 1, "access": "ro", "reset": 0x00000000},
            "done": {"lsb": 1, "width": 1, "access": "ro", "reset": 0x00000000},
            "err_lock": {"lsb": 2, "width": 1, "access": "ro", "reset": 0x00000000},
            "aborted": {"lsb": 3, "width": 1, "access": "ro", "reset": 0x00000000},
            "ld_now": {"lsb": 4, "width": 1, "access": "ro", "reset": 0x00000000},
            "wait_sample": {"lsb": 5, "width": 1, "access": "ro", "reset": 0x00000000},
            "err_table": {"lsb": 6, "width": 1, "access": "ro", "reset": 0x00000000},
            "pin_owner_act": {"lsb": 7, "width": 1, "access": "ro", "reset": 0x00000000},
            "state": {"lsb": 8, "width": 4, "access": "ro", "reset": 0x00000000},
        },
    },
    "N_ENTRIES": {
        "offset": 0x010,
        "ext": False,
        "fields": {
            "n": {"lsb": 0, "width": 16, "access": "rw", "reset": 0x00000000},
        },
    },
    "N_AVG": {
        "offset": 0x014,
        "ext": False,
        "fields": {
            "n": {"lsb": 0, "width": 12, "access": "rw", "reset": 0x00000001},
        },
    },
    "SPI_DIV": {
        "offset": 0x018,
        "ext": False,
        "fields": {
            "div": {"lsb": 0, "width": 8, "access": "rw", "reset": 0x00000005},
        },
    },
    "T_ATT_GAP_CYC": {
        "offset": 0x01C,
        "ext": False,
        "fields": {
            "cycles": {"lsb": 0, "width": 16, "access": "rw", "reset": 0x00000064},
        },
    },
    "T_MIN_US": {
        "offset": 0x020,
        "ext": False,
        "fields": {
            "us": {"lsb": 0, "width": 20, "access": "rw", "reset": 0x000000C8},
        },
    },
    "T_LOCK_STABLE_US": {
        "offset": 0x024,
        "ext": False,
        "fields": {
            "us": {"lsb": 0, "width": 20, "access": "rw", "reset": 0x00000032},
        },
    },
    "T_LOCK_TIMEOUT_US": {
        "offset": 0x028,
        "ext": False,
        "fields": {
            "us": {"lsb": 0, "width": 20, "access": "rw", "reset": 0x00002710},
        },
    },
    "T_SETTLE_US": {
        "offset": 0x02C,
        "ext": False,
        "fields": {
            "us": {"lsb": 0, "width": 20, "access": "rw", "reset": 0x000001F4},
        },
    },
    "PE4302": {
        "offset": 0x030,
        "ext": False,
        "fields": {
            "manual": {"lsb": 0, "width": 6, "access": "rw", "reset": 0x0000003F},
            "active_high": {"lsb": 8, "width": 1, "access": "rw", "reset": 0x00000001},
        },
    },
    "PIN_STATE": {
        "offset": 0x034,
        "ext": False,
        "fields": {
            "pe_in": {"lsb": 0, "width": 6, "access": "ro", "reset": 0x00000000},
            "ld": {"lsb": 8, "width": 1, "access": "ro", "reset": 0x00000000},
            "le": {"lsb": 9, "width": 1, "access": "ro", "reset": 0x00000000},
            "clk": {"lsb": 10, "width": 1, "access": "ro", "reset": 0x00000000},
            "dat": {"lsb": 11, "width": 1, "access": "ro", "reset": 0x00000000},
            "pe_out": {"lsb": 16, "width": 6, "access": "ro", "reset": 0x00000000},
            "pe_t": {"lsb": 24, "width": 6, "access": "ro", "reset": 0x00000000},
        },
    },
    "DET_CFG": {
        "offset": 0x038,
        "ext": False,
        "fields": {
            "src": {"lsb": 0, "width": 2, "access": "rw", "reset": 0x00000000},
        },
    },
    "DET_TEST": {
        "offset": 0x03C,
        "ext": False,
        "fields": {
            "base": {"lsb": 0, "width": 16, "access": "rw", "reset": 0x00000000},
        },
    },
    "DET_PUSH": {
        "offset": 0x040,
        "ext": True,
        "fields": {
            "sample": {"lsb": 0, "width": 16, "access": "rw", "reset": 0x00000000},
        },
    },
    "FIRST_ERR_INDEX": {
        "offset": 0x044,
        "ext": False,
        "fields": {
            "index": {"lsb": 0, "width": 16, "access": "ro", "reset": 0x00000000},
        },
    },
    "POINT_COUNT": {
        "offset": 0x048,
        "ext": False,
        "fields": {
            "count": {"lsb": 0, "width": 16, "access": "ro", "reset": 0x00000000},
        },
    },
    "SWEEP_COUNT": {
        "offset": 0x04C,
        "ext": False,
        "fields": {
            "count": {"lsb": 0, "width": 32, "access": "ro", "reset": 0x00000000},
        },
    },
    "ENTRY_INDEX": {
        "offset": 0x050,
        "ext": False,
        "fields": {
            "index": {"lsb": 0, "width": 16, "access": "ro", "reset": 0x00000000},
        },
    },
    "TABLE_ADDR": {
        "offset": 0x060,
        "ext": True,
        "fields": {
            "index": {"lsb": 0, "width": 16, "access": "rw", "reset": 0x00000000},
        },
    },
    "TABLE_W0": {
        "offset": 0x064,
        "ext": False,
        "fields": {
            "word": {"lsb": 0, "width": 32, "access": "rw", "reset": 0x00000000},
        },
    },
    "TABLE_W1": {
        "offset": 0x068,
        "ext": True,
        "fields": {
            "att": {"lsb": 0, "width": 6, "access": "rw", "reset": 0x00000000},
            "spi_en": {"lsb": 8, "width": 1, "access": "rw", "reset": 0x00000000},
            "att_en": {"lsb": 9, "width": 1, "access": "rw", "reset": 0x00000000},
            "measure": {"lsb": 10, "width": 1, "access": "rw", "reset": 0x00000000},
            "skip_lock": {"lsb": 11, "width": 1, "access": "rw", "reset": 0x00000000},
        },
    },
    "RESULT_ADDR": {
        "offset": 0x070,
        "ext": True,
        "fields": {
            "index": {"lsb": 0, "width": 16, "access": "rw", "reset": 0x00000000},
        },
    },
    "RESULT_DATA": {
        "offset": 0x074,
        "ext": True,
        "fields": {
            "sum": {"lsb": 0, "width": 28, "access": "ro", "reset": 0x00000000},
            "unlocked": {"lsb": 31, "width": 1, "access": "ro", "reset": 0x00000000},
        },
    },
    "CAPS": {
        "offset": 0x078,
        "ext": False,
        "fields": {
            "table_aw": {"lsb": 0, "width": 8, "access": "ro", "reset": 0x00000000},
            "result_aw": {"lsb": 8, "width": 8, "access": "ro", "reset": 0x00000000},
            "clk_mhz": {"lsb": 16, "width": 16, "access": "ro", "reset": 0x00000000},
        },
    },
}
