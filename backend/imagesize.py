"""Picture dimensions from the file header, without decoding the picture or needing an imaging library."""
import struct
from functools import lru_cache
from pathlib import Path


def _png(head):
    return struct.unpack('>II', head[16:24]) if head[:8] == b'\x89PNG\r\n\x1a\n' else None


def _gif(head):
    return struct.unpack('<HH', head[6:10]) if head[:6] in (b'GIF87a', b'GIF89a') else None


def _webp(head):
    if head[:4] != b'RIFF' or head[8:12] != b'WEBP':
        return None
    kind = head[12:16]
    if kind == b'VP8X':
        return 1 + int.from_bytes(head[24:27], 'little'), 1 + int.from_bytes(head[27:30], 'little')
    if kind == b'VP8L' and head[20] == 0x2F:
        bits = int.from_bytes(head[21:25], 'little')
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if kind == b'VP8 ':
        return struct.unpack('<HH', head[26:30])[0] & 0x3FFF, struct.unpack('<HH', head[26:30])[1] & 0x3FFF
    return None


def _jpeg(handle):
    handle.seek(0)
    if handle.read(2) != b'\xff\xd8':
        return None
    while True:
        byte = handle.read(1)
        if not byte:
            return None
        if byte != b'\xff':
            continue
        marker = handle.read(1)
        while marker == b'\xff':
            marker = handle.read(1)
        if not marker or marker in (b'\x01', *(bytes([n]) for n in range(0xD0, 0xD9))):
            continue
        length = handle.read(2)
        if len(length) < 2:
            return None
        size = struct.unpack('>H', length)[0]
        if 0xC0 <= marker[0] <= 0xCF and marker[0] not in (0xC4, 0xC8, 0xCC):
            data = handle.read(5)
            return (struct.unpack('>H', data[3:5])[0], struct.unpack('>H', data[1:3])[0]) if len(data) == 5 else None
        handle.seek(size - 2, 1)


@lru_cache(maxsize=2048)
def _measure(path, mtime):
    try:
        with open(path, 'rb') as handle:
            head = handle.read(32)
            found = _png(head) or _gif(head) or _webp(head) or _jpeg(handle)
    except (OSError, struct.error, IndexError):
        return None
    return found if found and found[0] > 0 and found[1] > 0 else None


def image_size(path):
    """(width, height) of a PNG, GIF, WebP or JPEG file, or None when it is something else or unreadable."""
    try:
        return _measure(str(path), Path(path).stat().st_mtime_ns)
    except OSError:
        return None


def image_ratio(path):
    size = image_size(path)
    return round(size[0] / size[1], 4) if size else None
