import io
import json
import struct
import sys

sys.path.insert(0, r"C:\AvatarProject\lip_sync_service")
from realtime_app import _parse_packet

jpegs = [b"\xff\xd8" + b"x" * 100 + b"\xff\xd9"] * 3
head = json.dumps({"kind": "speech", "fps": 25, "sr": 16000, "audio": 5,
                   "frames": [len(j) for j in jpegs]}).encode()
pkt = struct.pack(">I", len(head)) + head + b"abcde" + b"".join(jpegs)
keepalive = struct.pack(">I", 2) + b"{}"

buf = io.BytesIO()
buf.write(keepalive)
print("1:", _parse_packet(buf))
buf.write(pkt)
print("2:", _parse_packet(buf))
buf.write(pkt[:50])
print("3 (partial):", _parse_packet(buf))
buf.write(pkt[50:])
r = _parse_packet(buf)
print("4:", r[0], len(r[1]), "remaining:", buf.getvalue())
