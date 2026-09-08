import os
import shutil
import subprocess
import sys

def _convert(filename):
    COMMAND_NAME = "convert"

    if not shutil.which(COMMAND_NAME):
        print("ERROR: Cannot find imagemagick, attempting install now.")

        if os.getuid() != 0:
            print("ERROR: Run this script with sudo. exit code 1")
            sys.exit(1)

        try:
            print("updating...")
            subprocess.run(["apt-get", "install", "-y", "imagemagick"], check=True)
            print("Installed Imagemagick")
        except subprocess.CalledProcessError as e:
                print("Download Failed!! Exit code 2")
                sys.exit(2)
    try:
        print("Converting PNG to 4-bit grayscale")
        subprocess.run([COMMAND_NAME, filename, "-colorspace", "Gray", "-depth", "4", "work.png"], check=True)
        print("Sucessful Conversion!!")
    except subprocess.CalledProcessError as e:
            print("Conversion failed! Try again")
            sys.exit(3)
    return 0;

if __name__ == "__main__":
    _enforce("/home/dlw/git_files/NPU-Project/software/Data/color.png")
