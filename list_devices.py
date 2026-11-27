import sounddevice as sd

apis = sd.query_hostapis()
print("=== OUTPUT DEVICES ===")
for i, d in enumerate(sd.query_devices()):
    if d["max_output_channels"] > 0:
        print("%3d | api=%-12s | out=%2d | sr=%6.0f | %s" % (
            i, apis[d["hostapi"]]["name"], d["max_output_channels"],
            d["default_samplerate"], d["name"]))
print()
print("default output index:", sd.default.device[1])
