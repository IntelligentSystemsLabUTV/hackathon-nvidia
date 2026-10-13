"""Copies stdin to <log> and, with an epoch timestamp in front of every line, to <log minus .log>.tslog."""
import sys
import time

plain = open(sys.argv[1], "w", buffering=1)
stamped = open(sys.argv[1][: -len(".log")] + ".tslog", "w", buffering=1)
for line in sys.stdin:
    plain.write(line)
    stamped.write(f"{time.time():.1f} {line}")
