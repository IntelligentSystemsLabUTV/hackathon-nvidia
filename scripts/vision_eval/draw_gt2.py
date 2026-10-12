import json, sys, os
os.chdir(os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
import numpy as np
from PIL import Image, ImageDraw
gt = json.load(open("gt.json"))
out, names = sys.argv[1], sys.argv[2:]
W, H = 960, 540
DW, DH = 672, 376
cols = [(255,0,0),(0,200,0),(0,0,255),(255,0,255),(0,200,200),(255,140,0),(120,0,200),(0,120,60)]
sheet = Image.new("RGB", (2 * W, ((len(names) + 1) // 2) * H), "white")
for k, n in enumerate(names):
    im = Image.open(f"frames/{n}.png").resize((W, H)).convert("RGBA")
    over = Image.new("RGBA", (W, H), (0,0,0,0))
    d = ImageDraw.Draw(over)
    j = 0
    for o in gt[n]["objects"]:
        if not o.get("visible_box") or o["visible_px"] < 30:
            continue
        c = cols[j % len(cols)]; j += 1
        m = np.unpackbits(np.load(f"masks/{n}__{o['name']}.npy"))[:DW*DH].reshape(DH, DW)
        mi = Image.fromarray((m*90).astype(np.uint8)).resize((W, H))
        over.paste(Image.new("RGBA", (W, H), c + (255,)), (0,0), mi)
        b = o["visible_box"]
        d.rectangle([b[0]*W, b[1]*H, b[2]*W, b[3]*H], outline=c + (255,), width=2)
        d.text((b[0]*W + 3, b[1]*H + 2), f"{o['category']} {o['distance_m']}m {o['bearing_deg']}d px{o['visible_px']}", fill=c + (255,))
    im = Image.alpha_composite(im, over).convert("RGB")
    ImageDraw.Draw(im).text((5, 5), n, fill=(0, 0, 255))
    sheet.paste(im, ((k % 2) * W, (k // 2) * H))
sheet.save(out, quality=85)
