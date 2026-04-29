# gpio17_center_test.py
import time
import RPi.GPIO as GPIO

PIN = 17
GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.OUT)

pwm = GPIO.PWM(PIN, 50)
pwm.start(0)

try:
    pwm.ChangeDutyCycle(7.5)  # center
    time.sleep(10)
finally:
    pwm.ChangeDutyCycle(0)
    pwm.stop()
    GPIO.cleanup()
