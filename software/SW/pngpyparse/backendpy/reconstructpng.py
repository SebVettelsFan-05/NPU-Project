#ai gen based off of the deconstruction files

import struct
import zlib
import binascii


def make_png(filename, width, height, pixels, bit_depth):
    if bit_depth not in (1, 2, 4, 8, 16):
        return _error(f"unsupported bit depth: {bit_depth}")

    rows = bytearray()

    if bit_depth == 4:
        for y in range(height):
            rows.append(0)  # filter type

            row = pixels[y]

            for x in range(0, width, 2):
                high = row[x] & 0x0F
                low = row[x + 1] & 0x0F if x + 1 < width else 0

                rows.append((high << 4) | low)

    elif bit_depth == 8:
        for y in range(height):
            rows.append(0)
            rows.extend(pixel & 0xFF for pixel in pixels[y])

    elif bit_depth == 16:
        for y in range(height):
            rows.append(0)

            for pixel in pixels[y]:
                rows.extend(struct.pack(">H", pixel & 0xFFFF))

    else:
        return _error(
            f"packing for {bit_depth}-bit grayscale is not implemented"
        )

    def chunk(chunk_type, data):
        crc = binascii.crc32(chunk_type + data) & 0xFFFFFFFF

        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", crc)
        )

    png = bytearray()

    # PNG signature
    png.extend(b"\x89PNG\r\n\x1a\n")

    # IHDR
    ihdr = struct.pack(
        ">IIBBBBB",
        width,
        height,
        bit_depth,
        0,  # grayscale
        0,  # compression
        0,  # filter
        0   # non-interlaced
    )

    png.extend(chunk(b"IHDR", ihdr))

    # IDAT
    compressed = zlib.compress(bytes(rows))
    png.extend(chunk(b"IDAT", compressed))

    # IEND
    png.extend(chunk(b"IEND", b""))

    with open(filename, "wb") as f:
        f.write(png)
