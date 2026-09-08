import zlib
import struct

def _error(msg):
    print(f"ERROR: {msg}")
    return None
def _read_chunks(data):
    chunks = []

    pos = 8

    while pos < len(data):
        if pos + 8 > len(data):
            return _error("truncated PNG chunk header")

        length = struct.unpack(">I", data[pos:pos + 4])[0]
        chunk_type = data[pos + 4:pos + 8]

        start = pos + 8
        end = start + length

        if end + 4 > len(data):
            return _error("truncated PNG chunk")

        chunk_data = data[start:end]

        chunks.append((chunk_type, chunk_data))

        pos = end + 4  # skip CRC

    return chunks


def _read_ihdr(chunks):
    ihdr = None

    for chunk_type, chunk_data in chunks:
        if chunk_type == b"IHDR":
            ihdr = chunk_data
            break

    if ihdr is None:
        return _error("PNG has no IHDR chunk")

    if len(ihdr) != 13:
        return _error("invalid IHDR length")

    (
        width,
        height,
        bit_depth,
        color_type,
        compression,
        filter_method,
        interlace
    ) = struct.unpack(">IIBBBBB", ihdr)

    if width == 0 or height == 0:
        return _error("image has invalid dimensions")

    if bit_depth != 4:
        return _error(
            f"expected 4-bit grayscale, got {bit_depth}-bit"
        )

    if color_type != 0:
        return _error(
            f"expected grayscale PNG, got color type {color_type}"
        )

    if compression != 0:
        return _error("unsupported PNG compression method")

    if filter_method != 0:
        return _error("unsupported PNG filter method")

    if interlace != 0:
        return _error("interlaced PNGs are not supported")

    return width, height, bit_depth, color_type


def _get_idat(chunks):
    idat = bytearray()
    for chunk_type, chunk in chunks:
        if chunk_type == b"IDAT"
        idat.extend(chunk_data)
    if len(idat) == 0:
        _error("PNG has no IDAT")
    return bytes(idat)

def _decompress(idat):
    try:
        return zlib.decompress(idat)
    except zlib.error as e:
        _error(f"Cannot decompress IDAT {e}")


def _unfilter_row(filtered, previous, filter_type):

def _decode_scanlines(raw, width, height):

def paeth(left, up, up_left):

def unpack_pixels(rows, width):

def read_png(filename):
