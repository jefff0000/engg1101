import time
import RPi.GPIO as GPIO

PIN = 17   # try the bad servo pin
HZ = 50

GPIO.setmode(GPIO.BCM)
GPIO.setup(PIN, GPIO.OUT)
pwm = GPIO.PWM(PIN, HZ)
pwm.start(0)

def go(duty, t=2.0):
    pwm.ChangeDutyCycle(duty)
    time.sleep(t)

try:
    # small moves around center only
    go(7.5, 2)   # center
    go(7.0, 2)   # slight one way
    go(7.5, 2)
    go(8.0, 2)   # slight other way
    go(7.5, 2)
finally:
    pwm.ChangeDutyCycle(0)
    pwm.stop()
    GPIO.cleanup()
