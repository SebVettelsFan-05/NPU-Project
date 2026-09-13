from . import enforce as en
from . import convert as co
from . import read as re


def read_png(filename):
    data = en._enforce(filename)

    if data is None:
        return None

    if en._check_signature(data) is not True:
        return None

    chunks = re._read_chunks(data)

    if chunks is None:
        return None

    dimensions = re._read_ihdr(chunks)

    if dimensions is None:
        return None

    width, height, bitd, colord = dimensions

    idat = re._get_idat(chunks)

    if idat is None:
        return None

    raw = re._decompress(idat)

    if raw is None:
        return None

    rows = re._decode_scanlines(
        raw,
        width,
        height
    )

    if rows is None:
        return None

    pixels = re._unpack_pixels(
        rows,
        width
    )

    return width, height, pixels
