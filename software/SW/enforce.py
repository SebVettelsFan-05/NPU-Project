def _enforce(imagepath):
    try:
        with open(imagepath, "rb") as inputimg:
            data = inputimg.read()
        return data
    except OSError as e:
        print("Error, Could not open input PNG")
        return None

def _check_signature(data):
    if data[:8] != b'\x89PNG\r\n\x1a\n':
        raise ValueError("Not a PNG File")
    return True



