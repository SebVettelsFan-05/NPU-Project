"""Training data: clean images, a sensor noise model, and dataset assembly.

The clean images are synthetic by default. That is a deliberate choice, not
laziness: a 3x3 filter with sixteen 2-bit parameters has almost no capacity to
memorise anything, so what matters is that the training set contains the right
*local* structures (flat regions, straight edges, corners, gradients, fine
texture) in roughly realistic proportions. Photographs work too, and you can
supply them with --images, but they are not required.
"""

import numpy as np

# ---------------------------------------------------------------------------
# Sensor noise model
# ---------------------------------------------------------------------------
# Real sensor noise is signal dependent: photon arrival is Poisson, so the
# variance grows with brightness, and read noise adds a constant floor.
#
#     var(x) = shot * x + read          with x in [0, 1]
#
# Presets below are quoted by the resulting standard deviation at mid grey,
# expressed in 4-bit LSBs, which is the number that actually matters here.

NOISE_PRESETS = {
    "low":  dict(shot=0.0050, read=0.00090),   # ~0.9 LSB at mid grey
    "mid":  dict(shot=0.0120, read=0.00210),   # ~1.3 LSB
    "high": dict(shot=0.0300, read=0.00550),   # ~2.1 LSB
}


def noise_sigma_lsb(shot: float, read: float, level: float = 0.5) -> float:
    """Noise standard deviation in 4-bit LSBs at the given signal level."""
    return float(np.sqrt(shot * level + read) * 15.0)


def sense(clean: np.ndarray, shot: float, read: float, rng,
          compand_mode: str = "none") -> np.ndarray:
    """Apply the noise model, compand, and quantise to 4 bits.

    Order matters, and it is the order a real sensor pipeline uses:

        1. linear light, full precision
        2. add shot and read noise      <- the physics, only valid in linear
        3. compand                      <- allocates the few code values well
        4. quantise to 4 bits

    Skipping step 3 wastes most of the 16 available codes. On a typical indoor
    photograph, quantising *linear* light to 4 bits puts about 97% of pixels
    into codes 0 and 1; companding first spreads them across the range. Gamma
    encoding exists for exactly this reason, and it matters far more at 4 bits
    than at 8.

    ``compand_mode="none"`` means the input is already in a coded domain, so
    steps 1-3 collapse and the noise is added where the data already lives.
    That is the right setting for synthetic images and for photographs used
    without ``--linearise``; it is physically wrong about the noise, but it at
    least does not waste the codes.

    Returns int64 in 0..15.
    """
    sigma = np.sqrt(np.clip(shot * clean + read, 0.0, None))
    noisy = clean + sigma * rng.standard_normal(clean.shape)
    coded = compand(np.clip(noisy, 0.0, 1.0), compand_mode)
    return np.clip(np.round(coded * 15.0), 0, 15).astype(np.int64)


# ---------------------------------------------------------------------------
# Synthetic clean images, all returning float arrays in [0, 1]
# ---------------------------------------------------------------------------

def _rects(size, rng):
    """Overlapping flat rectangles: flat regions, straight edges, corners."""
    img = np.full((size, size), rng.uniform(0, 0.3))
    for _ in range(rng.integers(4, 10)):
        y, x = rng.integers(0, size, 2)
        h, w = rng.integers(size // 8, size // 2, 2)
        img[y:y + h, x:x + w] = rng.uniform(0, 1)
    return img


def _gradient(size, rng):
    """Smooth ramps: the case where over-aggressive filtering causes banding."""
    yy, xx = np.mgrid[0:size, 0:size] / (size - 1.0)
    a, b = rng.uniform(-1, 1, 2)
    return np.clip(0.5 + 0.4 * (a * xx + b * yy), 0, 1)


def _stripes(size, rng):
    """Hard edges at arbitrary angles and spacings."""
    yy, xx = np.mgrid[0:size, 0:size]
    theta = rng.uniform(0, np.pi)
    proj = xx * np.cos(theta) + yy * np.sin(theta)
    period = rng.uniform(3, size / 4)
    stripes = (np.sin(2 * np.pi * proj / period) > 0).astype(float)
    lo = rng.uniform(0, 0.4)
    return lo + stripes * rng.uniform(0.3, 1.0 - lo)


def _texture(size, rng):
    """Blocky detail near the pixel scale: what a filter can wrongly destroy."""
    block = rng.integers(2, 8)
    small = rng.uniform(0, 1, (size // block + 1, size // block + 1))
    return np.kron(small, np.ones((block, block)))[:size, :size]


def _disks(size, rng):
    """Curved edges, so the filter does not only ever see axis-aligned ones."""
    yy, xx = np.mgrid[0:size, 0:size]
    img = np.full((size, size), rng.uniform(0, 0.4))
    for _ in range(rng.integers(3, 8)):
        cy, cx = rng.integers(0, size, 2)
        r = rng.integers(size // 16 + 2, size // 4)
        img[(yy - cy) ** 2 + (xx - cx) ** 2 < r * r] = rng.uniform(0, 1)
    return img


GENERATORS = [_rects, _gradient, _stripes, _texture, _disks]


def synthetic_images(count: int, size: int, seed: int) -> np.ndarray:
    """Round-robin over the generators so every class is equally represented."""
    rng = np.random.default_rng(seed)
    out = [np.clip(GENERATORS[i % len(GENERATORS)](size, rng), 0, 1)
           for i in range(count)]
    return np.stack(out)


IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp"}


def list_images(directory: str, pattern: str = None) -> list:
    """Every usable image under ``directory``, recursively, in a stable order.

    Args:
        pattern: optional case-insensitive filename glob, e.g. ``*GT_SRGB*``.
                 Denoising datasets ship the clean and noisy versions of a shot
                 side by side in the same folder, so a bare recursive search
                 would sweep up the noisy ones as ground truth. Filter.
    """
    from fnmatch import fnmatch
    from pathlib import Path
    paths = sorted(p for p in Path(directory).rglob("*")
                   if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES)
    if not paths:
        raise SystemExit(f"no images found under {directory} "
                         f"(looked for {', '.join(sorted(IMAGE_SUFFIXES))})")
    if pattern:
        matched = [p for p in paths if fnmatch(p.name.lower(), pattern.lower())]
        if not matched:
            sample = ", ".join(p.name for p in paths[:4])
            raise SystemExit(
                f"pattern {pattern!r} matched none of the {len(paths)} images "
                f"under {directory}. Filenames look like: {sample}")
        print(f"  pattern {pattern!r}: {len(matched)} of {len(paths)} images kept")
        paths = matched
    return paths


def split_images(directory: str, holdout: float = 0.25, seed: int = 0,
                 pattern: str = None) -> tuple:
    """Split the photos into disjoint train and test sets.

    Splitting by *photograph*, not by crop. Cropping the same photo into both
    sets leaks: adjacent crops share lighting, focus, sensor and often content,
    so the test PSNR comes out flattering and you find out on silicon.
    """
    paths = list_images(directory, pattern)
    if len(paths) < 2:
        raise SystemExit(f"need at least 2 images to split, found {len(paths)}")
    order = np.random.default_rng(seed).permutation(len(paths))
    n_test = max(1, min(len(paths) - 1, int(round(len(paths) * holdout))))
    test = [paths[i] for i in order[:n_test]]
    train = [paths[i] for i in order[n_test:]]
    return train, test


COMPAND_MODES = ("none", "srgb", "gamma")


def compand(x: np.ndarray, mode: str = "none", gamma: float = 2.2) -> np.ndarray:
    """Linear light to code values, in [0, 1]. The inverse of the sensor's eye.

    ``srgb`` is the standard transfer function and the safe default. ``gamma``
    is a plain power curve, which is what a cheap sensor or a small ISP is more
    likely to implement in hardware. ``none`` passes through, for data that is
    already coded.
    """
    if mode not in COMPAND_MODES:
        raise ValueError(f"compand mode must be one of {COMPAND_MODES}")
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    if mode == "none":
        return x
    if mode == "gamma":
        return x ** (1.0 / gamma)
    return np.where(x <= 0.0031308, x * 12.92,
                    1.055 * np.power(x, 1.0 / 2.4) - 0.055)


def srgb_to_linear(c: np.ndarray) -> np.ndarray:
    """Undo the sRGB transfer function. Input and output both in [0, 1].

    The noise model ``var(x) = shot * x + read`` describes photons, so it only
    means anything in linear light. Ordinary photographs are gamma encoded, and
    applying the model to them directly overstates the noise in the shadows and
    understates it in the highlights.
    """
    c = np.asarray(c, dtype=np.float64)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


# Rec. 709 luminance weights. These apply to *linear* RGB. The luma weights
# baked into PIL's "L" conversion (Rec. 601) apply to gamma-encoded RGB and are
# a different quantity; do not mix them up.
REC709_LUMA = np.array([0.2126, 0.7152, 0.0722])


def _load_plane(path, linearise: bool) -> np.ndarray:
    """Load one photograph as a single float plane in [0, 1].

    Order matters. With ``linearise`` the sRGB curve is undone *per channel*
    first, and luminance is formed in linear light. Converting to grey first
    and applying the inverse curve to that grey is a different, wrong number.
    """
    from PIL import Image
    with Image.open(path) as im:
        if linearise:
            rgb = np.asarray(im.convert("RGB"), dtype=np.float64) / 255.0
            return srgb_to_linear(rgb) @ REC709_LUMA
        return np.asarray(im.convert("L"), dtype=np.float64) / 255.0


def _box_downsample(arr: np.ndarray, factor: int) -> np.ndarray:
    """Box-average by an integer factor, discarding any ragged remainder.

    Done here rather than in Pillow so that when ``--linearise`` is set the
    averaging happens in linear light, where averaging is the physically
    correct operation.
    """
    if factor <= 1:
        return arr
    h = arr.shape[0] // factor * factor
    w = arr.shape[1] // factor * factor
    return arr[:h, :w].reshape(h // factor, factor,
                               w // factor, factor).mean(axis=(1, 3))


def load_images(source, count: int, size: int, seed: int,
                linearise: bool = False, downscale: int = 1) -> np.ndarray:
    """Load greyscale crops from photographs. Requires Pillow.

    Args:
        source:    a directory, or an explicit list of paths from
                   :func:`split_images`.
        count:     how many crops to return.
        size:      crop edge in pixels.
        seed:      RNG seed for crop placement.
        linearise: undo the sRGB transfer function, so the noise model is
                   applied in linear light where it is physically meaningful.
        downscale: integer box-downsample factor applied before cropping.
                   Downscaling averages away the noise already present in the
                   photograph, which is what makes it usable as clean ground
                   truth. 2 or 3 is usually right for phone or DSLR images.

    Photographs are used as the *clean* target. The sensor noise is simulated on
    top by :func:`sense`. Feeding in already-noisy images trains the network to
    reproduce that noise, not to remove it.
    """
    from PIL import Image

    paths = list(source) if not isinstance(source, (str, bytes)) else list_images(source)
    rng = np.random.default_rng(seed)

    usable, skipped = [], []
    for path in paths:
        try:
            with Image.open(path) as img:
                w, h = img.size
        except OSError:
            skipped.append((path, "unreadable"))
            continue
        if min(w, h) // downscale < size:
            skipped.append((path, f"{w}x{h} too small after /{downscale}"))
            continue
        usable.append(path)

    if not usable:
        detail = "; ".join(f"{p.name}: {why}" for p, why in skipped[:5])
        raise SystemExit(
            f"no image is at least {size}x{size} after downscaling by "
            f"{downscale} ({len(skipped)} skipped). {detail}")
    if skipped:
        print(f"  skipped {len(skipped)} unusable image(s), using {len(usable)}")

    crops = []
    cache = {}
    # Cursor advances independently of how many crops have been kept, so a
    # rejected image can never wedge the loop.
    for i in range(count):
        path = usable[i % len(usable)]
        if path not in cache:
            # Decoding a 12-megapixel PNG per 64x64 crop is the difference
            # between seconds and minutes on a real dataset.
            cache[path] = _box_downsample(_load_plane(path, linearise), downscale)
        arr = cache[path]
        y = rng.integers(0, arr.shape[0] - size + 1)
        x = rng.integers(0, arr.shape[1] - size + 1)
        crops.append(arr[y:y + size, x:x + size])
    return np.stack(crops)


# ---------------------------------------------------------------------------
# Dataset assembly
# ---------------------------------------------------------------------------

class Dataset:
    """Flattened per-pixel training data.

    Attributes:
        cnt:    (N, 16) signed neighbour counts, from model.counts
        xc:     (N,)    4-bit centre values
        target: (N,)    clean value on the 6-bit output scale
        window: (N, 9)  raw 3x3 windows, kept for the linear baseline
    """

    def __init__(self, cnt, xc, target, window):
        self.cnt, self.xc, self.target, self.window = cnt, xc, target, window

    def __len__(self):
        return self.xc.size

    def subsample(self, n, seed=0):
        if n >= len(self):
            return self
        pick = np.random.default_rng(seed).choice(len(self), n, replace=False)
        return Dataset(self.cnt[pick], self.xc[pick],
                       self.target[pick], self.window[pick])


def build_dataset(clean_images, shot, read, seed) -> Dataset:
    """Add noise, quantise, and extract per-pixel features."""
    from model import counts

    rng = np.random.default_rng(seed)
    cnts, xcs, targets, windows = [], [], [], []

    for clean in clean_images:
        x4 = sense(clean, shot, read, rng)
        cnt, xc = counts(x4)
        cnts.append(cnt)
        xcs.append(xc)
        targets.append(np.round(clean.reshape(-1) * 63.0))
        padded = np.pad(x4, 1, mode="edge")
        h, w = x4.shape
        win = np.empty((xc.size, 9), dtype=np.float64)
        for j, (dy, dx) in enumerate([(a, b) for a in (-1, 0, 1) for b in (-1, 0, 1)]):
            win[:, j] = padded[1 + dy:1 + dy + h, 1 + dx:1 + dx + w].reshape(-1)
        windows.append(win)

    return Dataset(np.concatenate(cnts), np.concatenate(xcs),
                   np.concatenate(targets), np.concatenate(windows))
