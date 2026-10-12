"""YOLOE-26 (fixed vocabulary) tiled evaluation on house frames, all target categories."""
import importlib.util, json, os, sys
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("ye", os.path.join(HERE, "yolo_eval.py")); ye = importlib.util.module_from_spec(spec); spec.loader.exec_module(ye)
NAMES = ["refrigerator", "bed", "sofa", "television", "dining table", "chair", "wardrobe", "fitness machine", "barbell",
         "trash can", "nightstand", "desk", "door", "shoe rack", "coffee table", "fire hydrant", "traffic light", "stop sign"]
ye.CLASSES = {n: i for i, n in enumerate(NAMES)}
label, model = sys.argv[1], sys.argv[2]
sys.argv = [sys.argv[0], label, model]
ye.main()
