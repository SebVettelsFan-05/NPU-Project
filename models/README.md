# TinyTapeout denoising CNN NPU: training and export

Trains a three-layer int4 convolutional denoiser and emits it as Verilog, a C
header, and golden vectors for the RTL testbench.

This is the model for the **MAC-array NPU** in `Design+DV/`.

Requires `numpy` and `torch` (CPU is fine). Pillow is optional, and only if you
train on real photos.

## Getting the weights

```
python selftest.py                       # run this first
python train.py --noise mid --out weights_mid.json
python export.py weights_mid.json --verilog weights.vh --header weights.h
python vectors.py weights_mid.json --out vectors.txt
```

`train.py` writes the weights to JSON. That JSON *is* the network.
Everything downstream is generated from it.

Typical output:

```
noise 'mid': shot=0.0120 read=0.00210  ~1.3 LSB at mid grey
channels [1, 8, 8, 1]   int4 weights   uint4 activations   int16 accumulator

results on held-out test set
  unfiltered input        21.48 dB
  3x3 box blur            20.38 dB
  best linear 3x3         24.13 dB
  this CNN                26.96 dB

network: channels [1, 8, 8, 1]  720 weights  720 MACs/pixel
  shifts        [2, 3, 5]
  accumulator ranges observed on the test set:
    layer0_acc        -161 ..    146
    layer1_acc        -426 ..    333
    layer2_acc        -376 ..    482
    residual           -12 ..     15
  int16 headroom: -32768 .. 32767
```

The `best linear 3x3` line is the number that matters. It is the strongest
possible *linear* filter, fitted by least squares on the same data. A single
conv layer with no nonlinearity cannot beat it, so clearing it is the minimum
evidence that the depth and the ReLUs are earning their gates. If the CNN does
not clear it, more channels will not save you -- something is wrong.

Watch `3x3 box blur` too. If a plain average beats the CNN, your training
images are too smooth to contain the detail the filter is supposed to preserve.

## The network

Three 3x3 convolutions predicting a **residual** correction:

```
A0 = x4                                  uint4  0..15, 1 channel
A1 = requant(conv(A0, W0) + B0, sh0)     uint4  0..15, 8 channels
A2 = requant(conv(A1, W1) + B1, sh1)     uint4  0..15, 8 channels
r  = rshift(conv(A2, W2) + B2, sh2)      signed, 1 channel
y6 = clip(4*x4 + r, 0, 63)               uint6  0..63
```

Three 3x3 layers give a **7x7 receptive field**, which is what sizes the line
buffers.

The residual formulation is load-bearing twice over. At initialisation the
weights are near zero, so the network starts as an exact passthrough and
training only ever has to learn the correction — starting from a blur and
unlearning it converges far worse. And on silicon, an all-zero network *is* a
passthrough, which gives you a bring-up mode (below).

## Arithmetic

| quantity | width | range |
|---|---|---|
| weights | int4 | -8..7, stored biased as `w + 8` |
| activations | uint4 | 0..15 |
| bias | int8 | -128..127, folded into the accumulator |
| accumulator | int16 | signed |
| output | uint6 | 0..63 |

`requantise` is an arithmetic rounding right shift then a clip to 0..15.
**Clipping at zero is the ReLU** — they are the same operation, so the hardware
pays for one, not two.

The requantise shift is a per-layer power of two on purpose. A general
fixed-point rescale needs a multiplier in the requantise path; a shift needs
wiring. On a TinyTapeout tile that difference matters more than the accuracy it
costs. The shift is trained, not hand-tuned.

### Signed weights on your unsigned multiplier

`Design+DV/src/cmn/multiplier.sv` is an unsigned 4x4→8 array multiplier. CNN
weights must be signed. Rather than widen the multiplier, weights are stored
biased as `u = w + 8` (an unsigned nibble, 0..15) and the offset is removed in
one lump:

```
sum_i w_i * a_i  ==  sum_i u_i * a_i  -  8 * sum_i a_i
```

The left term is the multiplier you already have, unmodified. The right term is
a sum of activations shifted left by three — no multiplier at all, one extra
accumulator per output pixel.

`model.conv2d_unsigned` implements exactly this, and
`selftest.check_signed_unsigned_agree` asserts it is **bit-identical** to
the signed path over random networks. That check is what licenses using
`multiplier.sv` as-is.

## How the training works

Weights are int4: sixteen levels, no per-channel scale factor, and the
requantise is a bare shift. Post-training quantisation at that width does not
survive. So the integer datapath is simulated in the forward pass and
gradients are pushed through it with straight-through estimators:

```
w_int = clamp(round(w_raw), -8, 7)          STE on the round
s     = clamp(round(s_raw),  0, 15)         STE, the requantise shift
acc   = conv(a, w_int) + round(b_raw)
a_out = clamp(round(acc / 2^s), 0, 15)      clamp at 0 is the ReLU
```

Everything lives in integer units directly. There is no float weight scale to
fold anywhere: the per-layer shift *is* the scale, and it is trained alongside
the weights.

Two details worth keeping:

- The shift uses a **straight-through clamp**, the activations use a **real**
  clamp. Saturation is a genuine part of the datapath and the gradient should
  know about it; a shift that drifted out of range would otherwise be stranded
  there permanently with no gradient to bring it back.
- `--restarts` trains several independent initialisations and keeps whichever
  scores best **on the exact integer model**. STE training is noisier than
  ordinary training and individual runs land in visibly different places.

The reported PSNR is always measured with the bit-exact numpy model
(`evaluate_exact`), never with the torch surrogate. The headline number is the
number the silicon will produce.

## Retraining for your conditions

Three presets are built in, over the sensor model
`var(x) = shot * x + read` for a signal `x` in 0..1:

| preset | noise at mid grey | test PSNR |
|---|---|---|
| `--noise low` | 0.9 LSB | **29.66 dB** |
| `--noise mid` | 1.3 LSB | **26.96 dB** |
| `--noise high` | 2.1 LSB | **23.11 dB** |

All measured on the same held-out test set, with the bit-exact integer model.

Override the sensor model directly with `--shot` and `--read`. Calibrate these
from a flat-field capture at two exposures if you have the real sensor.

Change the shape with `--channels`, which must start and end at 1:

```
python train.py --channels 1,4,4,1 --out weights_small.json    # 216 MACs/px
python train.py --channels 1,8,8,1 --out weights_mid.json      # 720 MACs/px
```

To train on photographs instead of synthetic images:

```
python train.py --images /path/to/pngs --noise mid --out weights_mid.json
```

Synthetic is the default. The generators in `data.py` deliberately cover flat
regions, straight and curved edges, gradients and fine texture in sane
proportions. With 720 int4 weights this network *does* have enough capacity to
overfit, so representative photographs of your actual scene content are worth
using if you have them. See **Training on real photographs** below.

## Files

| file | what it does |
|---|---|
| `model.py` | The bit-exact integer datapath. Single source of truth. Pure numpy, no torch. |
| `train.py` | Quantisation-aware training with STE. CLI. Needs torch. |
| `export.py` | Weights to `weights.vh`, `weights.h`, and config words. |
| `vectors.py` | Golden vectors for the cocotb testbench. |
| `selftest.py` | Cross-checks the datapaths and the arithmetic invariants. |
| `demo.py` | Run a trained net on an image and look at the result. numpy + Pillow only. |
| `data.py` | Sensor noise model, synthetic images, and photo loading. |

`model.py` has no torch dependency on purpose. The RTL reference and the
vector generator must be runnable in any environment; only training needs torch.

## Looking at the result

```
python demo.py weights_high.json --image photo.png --noise high \
               --auto-crop --stretch --out demo.png
```

Writes a labelled panel -- clean, noisy 4-bit input, box blur, CNN output --
and prints a PSNR table. The numeric baselines in `train.py` tell you whether
the filter works; this tells you what it *looks* like, which catches failure
modes a scalar cannot: ringing, banding on gradients, smeared edges, blotching
in flat areas.

- `--auto-crop` picks the highest-variance region, so you judge the filter on
  edges and texture instead of on whatever blank wall the seed landed on.
- `--stretch` contrast-stretches the panel **for display only**, leaving the
  PSNRs untouched. Dark crops are otherwise impossible to read by eye, and the
  stretch range it prints is itself a useful diagnostic -- if the image only
  spans a few of the 63 output levels, your input tone mapping is wrong.
- `--already-noisy` skips the noise simulation for a real noisy capture. You
  get the picture but no PSNR, because there is no ground truth.
- `--full` processes the **whole** image instead of a crop, and `--separate`
  writes one file per tile rather than a very wide four-up panel. Use them
  together; `--full` forces `--scale 1`:

  ```
  python demo.py weights_high.json --image GT.PNG --noise high --linearise                  --full --separate --stretch --out full.png
  ```

  A full 2664x1500 frame takes about 16 seconds. `model.forward` on an image
  that size would allocate hundreds of megabytes of int64 accumulators, so
  `--full` runs the network in horizontal strips, each cut with a 3-pixel
  margin of real neighbouring pixels that is then discarded. The result is
  bit-identical to whole-image processing, which `forward_strips` is tested
  against. The accumulator ranges are then reported from a 256x256 probe window
  rather than the whole frame, and the panel is labelled accordingly.

Match `--downscale` and `--linearise` to whatever you trained with, or the
comparison is meaningless. It needs only numpy and Pillow, since `model.py` has
no torch dependency.

## Verification

`vectors.py` emits fifty hex values per line: the 49 pixels of a 7x7 patch
in raster order, then the expected 6-bit output for the **centre** pixel. Three
3x3 layers give a 7x7 receptive field, so a 7x7 patch determines one output
exactly, with no padding involved. Feed them to cocotb and assert **equality**,
not closeness.

Four things it does that random sampling would not:

- **Uniform patches at every level.** Under replicate padding these must come
  out uniform. A zero-padding bug shows up here immediately and nowhere else.
- **Single-hot patches** — one pixel differing from a flat field, at each of the
  49 positions. This is the closest thing to reading the impulse response off
  the silicon, and it catches transposed or mirrored kernel indexing, which a
  symmetric test pattern will never expose.
- **Row and column spikes**, which catch line-buffer ordering bugs.
- **A second pass under a saturating configuration.** The trained residual only
  spans about ±15, so the real weights barely touch the output clips. Since
  weights load at runtime a later reload can reach them, and untested silicon
  is not an option. The stress pass forces both clip paths.

Confirm the summary line reports a nonzero count at **both** floor and ceiling
before you consider the RTL verified. A default run reports something like
`output range 0..63 (2730 at floor, 2606 at ceiling)`.

`selftest.py` additionally checks, on random networks:

- the signed and unsigned-multiplier paths agree bit-for-bit
- the 7x7 patch path matches the full-image path at the centre pixel
- outputs always land in 0..63
- rounding is round-half-up including on negatives (`-3 >> 1` must be `-2`)
- uniform inputs stay uniform, so padding is replicate everywhere
- the **algebraic** worst-case accumulator fits int16, not merely the observed
  one — every weight at its extreme, every activation saturated

## Chip bring-up

`selftest.check_identity` verifies that an all-zero network is an exact
passthrough, where output equals `4 x input` everywhere. Load that on real
silicon first. It validates your line buffers, edge padding, channel ordering
and output packing independently of the convolution, so when something is wrong
you know which half to look at.

`model.Net.zeros()` builds that configuration.

## Gotchas

**Weights are transmitted biased.** Every stored weight is `w + 8`, an unsigned
nibble. Firmware and RTL must both know this. `export.py` is the only
definition of the layout and generates both files from it — keep it that way.
Ordering drift between firmware and RTL is the most common first-power-up
failure and it is entirely avoidable.

**`weight_order()` is the single definition of weight ordering**
(`[out_ch][in_ch][ky][kx]`). Anything that iterates weights goes through it.
`roundtrip_check` verifies the layout by actually inverting it rather than by
re-reading the packing code.

**The config payload is large.** 3028 bits, 253 twelve-bit words for a
`1,8,8,1` network. It loads once, but the
config shift register is real area — budget for it, and consider `--channels
1,4,4,1` (216 MACs/pixel and 948 bits, 79 words) if it does not fit.

**720 MACs per output pixel** is a throughput number, not an area number. With
`M` MAC units time-multiplexed you need `720/M` cycles per pixel. Size `M`
against your pixel clock and your tile budget.

**The generated `.vh` uses SystemVerilog unpacked array initialisation.** If
your flow is strict Verilog-2005, unroll it into individual assignments.

## Training on real photographs

```
python train.py --images /path/to/photos --noise mid --out weights_mid.json
```

The directory is searched **recursively**, so subfolders are fine.

### What images you need

The photographs are used as the **clean ground truth**. `data.py` simulates the
sensor noise on top of them. This is the part people get backwards: you do
*not* feed in noisy images. Training on already-noisy photos teaches the
network to reproduce that noise, because the noise is present in both the input
and the target.

So you want images that are as clean as possible:

- **Base ISO, good light, tripod or fast shutter.** Whatever your sensor does
  at ISO 100 is close enough to clean once downscaled.
- **Downscale.** `--downscale 2` is the default and does most of the work: box
  averaging by 2 cuts the noise already in the photo by about half while
  keeping real edges. For a modern phone or DSLR, 2 or 3 is right. Set
  `--downscale 1` only if your source is already small and clean.
- **Colour is handled in linear light.** With `--linearise`, the sRGB curve is
  undone per channel and Rec. 709 luminance is formed from *linear* RGB, then
  the box downsample averages in linear light too. Converting to grey first and
  applying the inverse curve to that grey is a different, wrong number — on a
  saturated pixel the two differ by tens of percent.
- **Content matters more than count.** Thirty varied photos beat three hundred
  of the same wall. You want flat regions, hard edges at many orientations,
  curved edges, smooth gradients and fine texture — the same mix the synthetic
  generators produce on purpose.
- **Anything under `--size` after downscaling is skipped**, with a count
  printed. Default `--size` is 64, so with `--downscale 2` you need photos of
  at least 128x128.

### Gamma

```
python train.py --images ./photos --linearise --noise mid --out weights.json
```

Ordinary photographs are sRGB gamma encoded. The noise model
`var(x) = shot * x + read` describes photon statistics, so it only means
anything in **linear light**. Applied to gamma-encoded pixels it overstates the
noise in the shadows and understates it in the highlights, and you get a filter
tuned for a sensor that does not exist.

Use `--linearise` if your chip will see linear sensor data, which is the usual
case for a raw pipeline. Leave it off if the chip sits *after* a gamma curve in
your ISP. It is off by default because that depends on your pipeline, not on
the images.

### Denoising datasets: filter to the clean images

Datasets built *for* denoising research (SIDD, DND, PolyU, RENOIR) ship the
clean and noisy versions of each shot **in the same folder**. The recursive
search will sweep up both, and the noisy ones will be used as ground truth —
which trains the network to reproduce noise rather than remove it, and fails
silently. Filter by filename:

```
python train.py --images ./SIDD_Small_sRGB --image-pattern '*GT_SRGB*' \
                --linearise --noise mid --out weights_mid.json
```

If the pattern matches nothing you get an error listing actual filenames from
the directory, so you can correct it without going hunting.

### Companding: why 4 bits needs a transfer curve

The pipeline is:

```
linear light  ->  add shot + read noise  ->  compand  ->  quantise to 4 bits
                  (the physics)             (allocates    (16 codes, total)
                                             the codes)
```

Step three is not optional. Quantising **linear light** straight to 4 bits is a
catastrophic waste of the 16 available codes, because linear light devotes most
of its range to highlights the eye barely distinguishes. On a typical indoor
SIDD frame:

| pipeline | 4-bit codes used | pixels stuck at code 0-1 |
|---|---|---|
| linear, no companding | 9 / 16 | 72.9% |
| linear + `--compand gamma` | 12 / 16 | 32.6% |
| linear + `--compand srgb` | 12 / 16 | 34.1% |

Without companding the network trains on what is effectively a 1.5-bit image.
It will still learn *something*, and the PSNR will even look good, but it is
solving a far easier problem than the silicon will face.

So `--compand` defaults to `srgb` whenever `--linearise` is set, and to `none`
otherwise. `gamma` is a plain power curve, which is closer to what a small ISP
or a cheap sensor actually implements in hardware; it scores about the same, so
pick whichever matches your pipeline.

`train.py` prints the code usage every run:

```
compand 'srgb': 12/16 four-bit codes used by the training set
```

If that number is low, stop and fix the tone handling before reading any PSNR.
The target is companded too — the chip consumes coded 4-bit values and emits
coded 6-bit ones, so asking it to output linear light would be asking it to
undo the companding as well as denoise.

`demo.py` warns if you run it with a different `--compand` than the weights
were trained with.

### Train/test split

Photos are split **by file**, not by crop, with `--holdout 0.25` reserving a
quarter of them for the test set. Cropping one photograph into both sets leaks:
adjacent crops share lighting, focus, sensor and often content, so the test
PSNR comes out flattering and you only find out on silicon.

This means you need **at least two photographs**, and realistically a dozen or
more for the held-out number to mean anything.

### Sanity checks on the result

Compare against the same run on synthetic data. The `best linear 3x3` baseline
should still fall. If it does not, or if `3x3 box blur` wins, your images are
too smooth — downscaled too hard, or all sky and blank wall — and the network
has learned to blur because on that data blurring is genuinely optimal.

Real photographs are also worth a second look at the accumulator ranges printed
at the end. They are content dependent, and `check_acc_width` in the selftest
only proves the *algebraic* worst case fits; the observed range tells you how
much of int16 you are actually using.

### Useful options

| option | default | what it does |
|---|---|---|
| `--images DIR` | — | photo directory, searched recursively |
| `--image-pattern G` | — | filename glob, e.g. `'*GT_SRGB*'` — see above |
| `--downscale N` | 2 | box-downsample before cropping, to clean the source |
| `--linearise` | off | undo sRGB gamma before applying the noise model |
| `--holdout F` | 0.25 | fraction of photos held out for test |
| `--train-images N` | 60 | number of training crops |
| `--test-images N` | 20 | number of test crops |
| `--size N` | 64 | crop edge in pixels |
