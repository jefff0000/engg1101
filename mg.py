import time
import RPi.GPIO as GPIO

HZ = 50

# Test both pins in sequence
PINS = [17, 27]

# PASS 1: higher than "safe" range (stronger motion)
PASS1 = {
    "center": 7.5,
    "left": 4.0,
    "right": 11.0,
}

# PASS 2 (optional): even wider "boost" (use briefly)
PASS2 = {
    "center": 7.5,
    "left": 3.0,
    "right": 12.0,
}

HOLD_SEC = 2.0
BETWEEN_PINS_SEC = 2.0


def run_pass(pin: int, duty_map: dict, label: str):
    print(f"\n=== GPIO{pin} {label} ===")
    GPIO.setup(pin, GPIO.OUT)

    pwm = GPIO.PWM(pin, HZ)
    pwm.start(0)

    def set_duty(name: str):
        d = duty_map[name]
        print(f"GPIO{pin}: {name} duty={d:.2f}%")
        pwm.ChangeDutyCycle(d)
        time.sleep(HOLD_SEC)

    try:
        # center -> left -> center -> right -> center
        set_duty("center")
        set_duty("left")
        set_duty("center")
        set_duty("right")
        set_duty("center")

        # release the servo (stop driving) for a moment
        print(f"GPIO{pin}: releasing (duty=0)")
        pwm.ChangeDutyCycle(0)
        time.sleep(1.0)

    finally:
        pwm.stop()
        # leave pin as input to avoid floating output states after PWM stops
        GPIO.setup(pin, GPIO.IN)
        print(f"GPIO{pin}: done")


def main():
    GPIO.setmode(GPIO.BCM)
    GPIO.setwarnings(False)

    try:
        for pin in PINS:
            run_pass(pin, PASS1, "PASS1 (4.0..11.0)")
            time.sleep(BETWEEN_PINS_SEC)

        print("\nIf there was still no movement, trying PASS2 (3.0..12.0) briefly...\n")
        for pin in PINS:
            run_pass(pin, PASS2, "PASS2 (3.0..12.0)")
            time.sleep(BETWEEN_PINS_SEC)

    finally:
        GPIO.cleanup()
        print("\nAll done.")


if __name__ == "__main__":
    main()
