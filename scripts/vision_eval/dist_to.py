"""Print the ground-truth distance from the robot centre to a target centre (evaluation only)."""
import math
import re
import sys

m = re.search(r"x=([-0-9.]+) y=([-0-9.]+)", sys.argv[1])
px, py = float(m.group(1)), float(m.group(2))
tx, ty = float(sys.argv[2]), float(sys.argv[3])
print(f"robot centre -> target centre: {math.hypot(tx - px, ty - py):.2f} m")
