import sys
import soundfile as sf
import sounddevice as sd

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 play_sound_sd_sf.py path/to/file.wav [device_index]", flush=True)
        print("\nDevices:", flush=True)
        print(sd.query_devices(), flush=True)
        sys.exit(2)

    path = sys.argv[1]
    device = int(sys.argv[2]) if len(sys.argv) >= 3 else None

    data, sr = sf.read(path, dtype="float32", always_2d=True)

    sd.play(data, samplerate=sr, device=device, blocking=True)
    sd.wait()

if __name__ == "__main__":
    main()
