from pngpyparse.frontendpy import readpng as pnr
from pngpyparse.backendpy import reconstructpng as recon
import split as split
result = pnr.read_png("work.png")

if result is None:
    sys.exit(3)

w,h,p = result

print(f"width x height = {w} x {h}")
print(type(p))
with open("pixels.txt", "w") as f:
    f.write("\n".join(str(x) for x in p) + "\n")

recon.make_png("recon.png", w, h, p, 4)
d, y1, x1 = split._splitArr(p)
split._sendArr(d)
