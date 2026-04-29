import time
import signal

import cv2
from ultralytics import YOLO

import board
import busio
from adafruit_vl53l0x import VL53L0X

import sounddevice as sd
import soundfile as sf

import RPi.GPIO as GPIO

# =========================
# CONFIG
# =========================
MODEL_PATH = "best.pt"
VOICE_DIR = "voices"

# Model class IDs -> names used for printing + audio filenames:
# voices/paper.wav, voices/plastic.wav, voices/can.wav
LABELS = {0: "paper", 1: "plastic", 2: "can"}

# VL53L0X activation distance — 70mm
DISTANCE_THRESHOLD_MM = 70

# YOLO
CONFIDENCE_THRESHOLD = 0.5
YOLO_IMGSZ = 320
RESIZE_FOR_YOLO = (320, 240)

# Stability
STABLE_FRAMES_REQUIRED = 10

# Servo pins (BCM)
GPIO_MODE = GPIO.BCM
SERVO1_PIN = 17
SERVO2_PIN = 27
PWM_HZ = 50

# Direction per-servo (flip SERVO2_DIR to 1 if your servo2 is not reversed)
SERVO1_DIR = 1
SERVO2_DIR = -1

# Calibrated duty window (your PASS1 worked and PASS2 failed)
DUTY_MIN = 4.0
DUTY_MAX = 11.0

# Rest angles
REST_ANGLE_1 = 0
REST_ANGLE_2 = 0

# Edge angles
EDGE_ANGLE = 80  # use -80 and +80

# Movement timing (instant set then wait)
SERVO_REACH_SEC = 1.5

# Post-return wait before sleep
SLEEP_AFTER_RESET_SEC = 1.0

# Audio
AUDIO_DEVICE = None
AUDIO_GAIN = 2.0

# I2C recovery tuning (best-effort; true fix is power + wiring)
I2C_RECOVER_SLEEP_SEC = 0.2
I2C_REINIT_RETRIES = 3

running = True


def handle_sigint(sig, frame):
    global running
    running = False


def log(msg):
    print(msg, flush=True)


# =========================
# AUDIO
# =========================
class AudioPlayer:
    def __init__(self, voice_dir, device=None, gain=1.0):
        self.voice_dir = voice_dir
        self.device = device
        self.gain = float(gain)
        self.cache = {}

    def _load(self, filename):
        if filename in self.cache:
            return self.cache[filename]
        path = f"{self.voice_dir}/{filename}"
        data, sr = sf.read(path, dtype="float32", always_2d=True)
        if self.gain != 1.0:
            data = (data * self.gain).clip(-1.0, 1.0)
        self.cache[filename] = (data, sr)
        return self.cache[filename]

    def play(self, filename, block=False):
        try:
            data, sr = self._load(filename)
            sd.play(data, samplerate=sr, device=self.device, blocking=block)
            if block:
                sd.wait()
        except Exception as e:
            log(f"Audio error ({filename}): {e}")


# =========================
# SERVO
# =========================
def clamp(x, lo, hi):
    return lo if x < lo else hi if x > hi else x


def angle_to_duty(angle_deg: float) -> float:
    """
    Map angle [-90, 90] -> duty [DUTY_MIN, DUTY_MAX].
    """
    a = clamp(float(angle_deg), -90.0, 90.0)
    t = (a + 90.0) / 180.0
    return DUTY_MIN + t * (DUTY_MAX - DUTY_MIN)


class MG90S:
    def __init__(self, bcm_pin: int, direction: int = 1, pwm_hz: int = 50, initial_angle: float = 0.0):
        self.pin = int(bcm_pin)
        self.dir = 1 if direction >= 0 else -1
        GPIO.setup(self.pin, GPIO.OUT)
        self.pwm = GPIO.PWM(self.pin, int(pwm_hz))
        self.pwm.start(0)
        self.current_angle = float(initial_angle)

    def set_angle(self, angle_deg: float):
        cmd_angle = float(angle_deg) * self.dir
        duty = angle_to_duty(cmd_angle)
        GPIO.output(self.pin, True)
        self.pwm.ChangeDutyCycle(duty)
        self.current_angle = float(angle_deg)

    def off(self):
        # Explicitly disable output (no pulses)
        GPIO.output(self.pin, False)
        self.pwm.ChangeDutyCycle(0)

    def stop(self):
        try:
            self.off()
        except Exception:
            pass
        try:
            self.pwm.stop()
        except Exception:
            pass


def servos_off(servo1: MG90S, servo2: MG90S):
    servo1.off()
    servo2.off()


def move_servo_instant(servo: MG90S, angle: float):
    servo.set_angle(angle)
    time.sleep(SERVO_REACH_SEC)


def move_to_target_servo1_first(servo1: MG90S, servo2: MG90S, a1: float, a2: float):
    move_servo_instant(servo1, a1)
    move_servo_instant(servo2, a2)


def move_to_rest_servo2_first(servo1: MG90S, servo2: MG90S):
    move_servo_instant(servo2, REST_ANGLE_2)
    move_servo_instant(servo1, REST_ANGLE_1)


# =========================
# DETECTION
# =========================
def signature_class_ids(results):
    ids = []
    for r in results:
        for b in r.boxes:
            ids.append(int(b.cls))
    ids.sort()
    return ids


def signature_to_labels(sig):
    return [LABELS.get(i, f"class{i}") for i in sig]


def decide_angles_from_label(label: str):
    """
    Updated per your request:

      can    -> (-EDGE_ANGLE, -EDGE_ANGLE)
      plastic-> (0, EDGE_ANGLE)
      paper  -> (EDGE_ANGLE, EDGE_ANGLE)   (unchanged from previous swap)
    """
    if label == "can":
        return (-EDGE_ANGLE, -EDGE_ANGLE)
    if label == "plastic":
        return (0, EDGE_ANGLE)
    if label == "paper":
        return (EDGE_ANGLE, EDGE_ANGLE)
    return None


# =========================
# I2C / VL53L0X with recovery
# =========================
def init_vl53():
    i2c = busio.I2C(board.SCL, board.SDA)
    sensor = VL53L0X(i2c)
    return i2c, sensor


def safe_distance_read(i2c, sensor):
    """
    Returns (i2c, sensor, distance_mm or None)
    Retries by reinitializing I2C+sensor if read fails.
    """
    try:
        return i2c, sensor, sensor.distance
    except Exception as e:
        log(f"I2C distance read error: {e}")

    time.sleep(I2C_RECOVER_SLEEP_SEC)

    for attempt in range(1, I2C_REINIT_RETRIES + 1):
        try:
            i2c, sensor = init_vl53()
            d = sensor.distance
            log(f"I2C/VL53L0X recovered on attempt {attempt}, distance={d} mm")
            return i2c, sensor, d
        except Exception as e2:
            log(f"I2C re-init attempt {attempt} failed: {e2}")
            time.sleep(I2C_RECOVER_SLEEP_SEC)

    return i2c, sensor, None


# =========================
# INIT
# =========================
def open_camera():
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        log("Camera not detected.")
        return None
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
    log("Camera opened")
    return cap


def close_camera(cap):
    try:
        cap.release()
    except Exception:
        pass
    log("Camera closed")


def init_model():
    try:
        model = YOLO(MODEL_PATH)
        log("YOLO model loaded")
        return model
    except Exception as e:
        log(f"YOLO load failed: {e}")
        return None


def init_servos():
    GPIO.setmode(GPIO_MODE)
    GPIO.setwarnings(False)
    s1 = MG90S(SERVO1_PIN, direction=SERVO1_DIR, pwm_hz=PWM_HZ, initial_angle=0.0)
    s2 = MG90S(SERVO2_PIN, direction=SERVO2_DIR, pwm_hz=PWM_HZ, initial_angle=0.0)
    s1.off()
    s2.off()
    log("Servos ready (OFF)")
    return s1, s2


# =========================
# MAIN
# =========================
def main():
    global running
    signal.signal(signal.SIGINT, handle_sigint)

    log("Initializing...")
    model = init_model()
    servo1, servo2 = init_servos()
    audio = AudioPlayer(VOICE_DIR, device=AUDIO_DEVICE, gain=AUDIO_GAIN)

    try:
        i2c, sensor = init_vl53()
        log(f"VL53L0X OK. Initial distance: {sensor.distance} mm")
    except Exception as e:
        log(f"VL53L0X init failed: {e}")
        return

    if not (model and servo1 and servo2 and sensor):
        log("Init failed. Exiting.")
        return

    cap = None
    mode = "sleep"
    last_sig = None
    stable_frames = 0

    log("Entering sleep mode")

    try:
        while running:
            # Servos OFF whenever reading sensors / running camera
            servos_off(servo1, servo2)

            if mode == "sleep":
                if cap is not None:
                    close_camera(cap)
                    cap = None

                i2c, sensor, dist = safe_distance_read(i2c, sensor)
                if dist is None:
                    time.sleep(0.1)
                    continue

                if dist <= DISTANCE_THRESHOLD_MM:
                    cap = open_camera()
                    if cap is None:
                        time.sleep(0.2)
                        continue
                    mode = "ready"
                    last_sig = None
                    stable_frames = 0
                    log("Entering ready mode")
                else:
                    time.sleep(0.1)
                    continue

            ok, frame = cap.read()
            if not ok:
                time.sleep(0.01)
                continue

            frame = cv2.resize(frame, RESIZE_FOR_YOLO)

            results = model(frame, conf=CONFIDENCE_THRESHOLD, imgsz=YOLO_IMGSZ, verbose=False)
            sig = signature_class_ids(results)

            print(signature_to_labels(sig), flush=True)

            if sig == last_sig:
                stable_frames += 1
            else:
                last_sig = sig
                stable_frames = 1

            if stable_frames < STABLE_FRAMES_REQUIRED:
                continue

            # Stable => ACTUATE
            if sig == []:
                move_to_rest_servo2_first(servo1, servo2)
                servos_off(servo1, servo2)
                time.sleep(SLEEP_AFTER_RESET_SEC)

                mode = "sleep"
                last_sig = None
                stable_frames = 0
                continue

            uniq = sorted(set(sig))
            if len(uniq) != 1:
                servos_off(servo1, servo2)
                audio.play("rubbish.wav", block=True)
                move_to_rest_servo2_first(servo1, servo2)
                servos_off(servo1, servo2)
                time.sleep(SLEEP_AFTER_RESET_SEC)

                mode = "sleep"
                last_sig = None
                stable_frames = 0
                continue

            cls_id = uniq[0]
            name = LABELS.get(cls_id, f"class{cls_id}")
            angles = decide_angles_from_label(name)
            if angles is None:
                move_to_rest_servo2_first(servo1, servo2)
                servos_off(servo1, servo2)
                time.sleep(SLEEP_AFTER_RESET_SEC)

                mode = "sleep"
                last_sig = None
                stable_frames = 0
                continue

            a1, a2 = angles

            # 1) Move to target
            move_to_target_servo1_first(servo1, servo2, a1, a2)

            # 2) Turn servos OFF during audio
            servos_off(servo1, servo2)

            # 3) Play audio AFTER first move, blocking
            audio.play(f"{name}.wav", block=True)

            # 4) Move back to rest, then OFF again
            move_to_rest_servo2_first(servo1, servo2)
            servos_off(servo1, servo2)

            # 5) Wait then sleep
            time.sleep(SLEEP_AFTER_RESET_SEC)

            mode = "sleep"
            last_sig = None
            stable_frames = 0

    finally:
        log("Shutting down...")
        try:
            if cap is not None:
                close_camera(cap)
        except Exception:
            pass
        try:
            sd.stop()
        except Exception:
            pass
        try:
            servo1.stop()
            servo2.stop()
        except Exception:
            pass
        GPIO.cleanup()


if __name__ == "__main__":
    main()
