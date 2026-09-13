import readpng as pnr
import reconstructpng as recon
result = pnr.read_png("work.png")

if result is None:
    sys.exit(3)

w,h,p = result

print(f"width x height = {w} x {h}")

with open("pixels.txt", "w") as f:
    f.write("\n".join(str(x) for x in p) + "\n")

recon.make_png("recon.png", w, h, p, 4)
