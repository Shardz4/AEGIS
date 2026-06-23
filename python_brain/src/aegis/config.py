import os

HEADER_SIZE = 64
OFFSET_WRITE_POS = 0
OFFSET_READ_POS = 8
OFFSET_CAPACITY = 16
OFFSET_EVENT_COUNT = 24

DEFAULT_RING_SIZE = 64 * 1024 * 1024
DEFAULT_RING_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "aegis_ring.bin"
    )
)

def get_ring_path():
    return os.environ.get("AEGIS_RING_PATH", DEFAULT_RING_PATH)

def get_ring_size():
    try:
        return int(os.environ.get("AEGIS_RING_SIZE", str(DEFAULT_RING_SIZE)))
    except ValueError:
        return DEFAULT_RING_SIZE
