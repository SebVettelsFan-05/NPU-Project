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
        if chunk_type == b"IDAT":
            idat.extend(chunk)
    if len(idat) == 0:
        _error("PNG has no IDAT")
    return bytes(idat)

def _decompress(idat):
    try:
        return zlib.decompress(idat)
    except zlib.error as e:
        _error(f"Cannot decompress IDAT {e}")


def _unfilter_row(filtered, previous, filter_type):
    row = bytearray(len(filtered))

    for x in range(len(filtered)):
        current = filtered[x]

        left = row[x - 1] if x > 0 else 0
        up = previous[x] if previous is not None else 0
        up_left = previous[x - 1] if x > 0 and previous is not None else 0

        if filter_type == 0:
            value = current

        elif filter_type == 1:
            value = current + left

        elif filter_type == 2:
            value = current + up

        elif filter_type == 3:
            value = current + ((left + up) // 2)

        elif filter_type == 4:
            value = current + _paeth(left, up, up_left)

        else:
            return _error(
                f"unsupported PNG filter type {filter_type}"
            )

        row[x] = value & 0xFF

    return row
def _decode_scanlines(raw, width, height):
    # 4-bit grayscale = 2 pixels per byte
    row_bytes = (width + 1) // 2

    expected_size = height * (row_bytes + 1)

    if len(raw) != expected_size:
        return _error(
            f"invalid decompressed size: "
            f"got {len(raw)}, expected {expected_size}"
        )

    pixels = []

    pos = 0
    previous = None

    for y in range(height):
        filter_type = raw[pos]
        pos += 1

        filtered = raw[pos:pos + row_bytes]
        pos += row_bytes

        row = _unfilter_row(
            filtered,
            previous,
            filter_type
        )

        if row is None:
            return None

        pixels.append(row)
        previous = row

    return pixels
def _paeth(left, up, up_left):
    p = left + up - up_left

    pa = abs(p - left)
    pb = abs(p - up)
    pc = abs(p - up_left)

    if pa <= pb and pa <= pc:
        return left

    if pb <= pc:
        return up

    return up_left

def _unpack_pixels(rows, width):
    pixels = []

    for row in rows:
        pixel_row = []

        for byte in row:
            pixel_row.append(byte >> 4)
            pixel_row.append(byte & 0x0F)

        # Remove the unused nibble if width is odd
        pixels.append(pixel_row[:width])

    return pixels
