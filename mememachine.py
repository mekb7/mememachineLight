import json
import os
import shutil
import textwrap
import time
from datetime import datetime
from pathlib import Path
from signal import pause
from threading import Thread
from urllib.error import URLError
from urllib.request import urlopen

import openai
import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from escpos.printer import Usb
from gpiozero import Button
from gpiozero.pins.pigpio import PiGPIOFactory
from usb.core import find as finddev

from outcome_interpreter import OutcomeGenerator

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

# Globals
openai.organization = os.getenv("OPENAI_ORG")
openai.api_key = os.getenv("OPENAI_API_KEY")

# Pin Factory
os.system('if pgrep pigpiod; then sudo killall pigpiod; fi')
time.sleep(1)
os.system('sudo pigpiod')
time.sleep(1)
pigpio_factory = PiGPIOFactory()

# Button
random_button = Button(4, bounce_time=0.1, pin_factory=pigpio_factory)

# POS Printer
dev = finddev(idVendor=0x04b8, idProduct=0x0202)
dev.reset()
time.sleep(2)
""" Seiko Epson Corp. Receipt Printer (EPSON TM-T88V) """
printer = Usb(0x04b8, 0x0202)

# Outcome Interpreter
with open("resources/template.json") as f:
    template_json = json.load(f)

outcome_generator = OutcomeGenerator(template_json)


def wait_for_internet_connection():
    while True:
        try:
            response = urlopen('https://google.com', timeout=2)
            return
        except URLError:
            print("Waiting for internet...")
            pass


def add_meme_text(image, top_text, bottom_text):
    # Load the image
    image_width, image_height = image.size

    # Determine the font size based on image width
    font_size_top = max(int(-0.9 * len(top_text) + 50), 25)
    font_size_bottom = max(int(-0.9 * len(bottom_text) + 50), 25)

    # Create a PIL ImageFont object
    font_top = ImageFont.truetype("resources/arial.ttf", font_size_top)
    font_bottom = ImageFont.truetype("resources/arial.ttf", font_size_bottom)

    # Create a PIL ImageDraw object
    draw = ImageDraw.Draw(image)

    # Calculate the maximum width for the text
    max_width = int(image_width * 0.05)

    # Add top text
    y = int(image_height * 0.05)
    for line in textwrap.wrap(top_text, width=max_width):
        draw.text((int(image_width * 0.1), y), line, font=font_top, align='center', fill='white', stroke_width=2,
                  stroke_fill='black')
        left, top, right, bottom = font_top.getbbox(line)
        height_line = bottom - top
        y += height_line

    # Add bottom text
    y = int(image_height * 0.95)
    bottom_lines = textwrap.wrap(bottom_text, width=max_width)
    left, top, right, bottom = font_top.getbbox(bottom_text)
    height_bottom_text = bottom - top
    bottom_offset = (len(bottom_lines) * height_bottom_text)
    for line in bottom_lines:
        draw.text((int(image_width * 0.1), y - bottom_offset), line, font=font_bottom, align="center", fill='white',
                  stroke_width=2,
                  stroke_fill='black')
        left, top, right, bottom = font_top.getbbox(line)
        height_line = bottom - top
        y += height_line

    return image


def print_text(text):
    printer.text(text)
    printer.cut()


def print_image(image):
    printer.image(image, impl='graphics')
    printer.cut()


def get_image_for_prompt(prompt):
    print("Returning image for prompt: " + prompt)
    try:
        response = openai.Image.create(
            prompt=prompt,
            n=1,
            size="512x512"
        )
        image_url = response['data'][0]['url']
        res = requests.get(image_url, stream=True)
        target_url = "generated/image_%s.jpg" % datetime.now().strftime("%Y%m%d_%H%M%S")
        if res.status_code == 200:
            with open(target_url, 'wb') as file:
                shutil.copyfileobj(res.raw, file)
            return Image.open(target_url)
        else:
            print('Image Couldn\'t be retrieved')
    except Exception as e:
        print(e)


def print_for_prompt(prompt):
    print("Printing image for prompt: " + prompt)
    try:
        response = openai.Image.create(
            prompt=prompt,
            n=1,
            size="512x512"
        )
        image_url = response['data'][0]['url']
        res = requests.get(image_url, stream=True)
        target_url = "generated/meme_%s.jpg" % datetime.now().strftime("%Y%m%d_%H%M%S")
        if res.status_code == 200:
            with open(target_url, 'wb') as file:
                shutil.copyfileobj(res.raw, file)
            printer.image(target_url, impl='graphics')
            printer.cut()
        else:
            print('Image couldn\'t be retrieved')
    except Exception as e:
        print(e)


def get_text_for_prompt(system_prompt, prompt):
    text = None
    for i in range(5):
        try:
            completion = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                temperature=1,
                max_tokens=60,
                frequency_penalty=0,
                presence_penalty=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ]
            )
            print(completion)
            text = json.loads(completion.choices[0].message.content)
        except:
            text = "Error"
            continue
        else:
            break
    print(text)
    return text


def get_meme_text_for_prompt(system_prompt, prompt):
    text_json = None
    for i in range(5):
        try:
            completion = openai.ChatCompletion.create(
                model="gpt-3.5-turbo",
                temperature=1,
                max_tokens=60,
                frequency_penalty=0,
                presence_penalty=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ]
            )
            print(completion)
            text_json = json.loads(completion.choices[0].message.content)
        except:
            text_json = {"text_top": "Error", "text_bottom": "Error"}
            continue
        else:
            break
    print(text_json)
    return text_json


def outcome_handler(outcome):
    match outcome.type:
        case "text":
            text = get_text_for_prompt(outcome["systemPromptRendered"], outcome["promptRendered"])
            print_text(text)
            return
        case "image":
            im = get_image_for_prompt(outcome["promptRendered"])
            print_image(im)
            return
        case "meme":
            im = get_image_for_prompt(outcome["promptRendered"])
            meme_json = get_meme_text_for_prompt(outcome["systemPromptRendered"], outcome["promptRendered"])
            add_meme_text(im, meme_json['text_top'], meme_json['text_bottom'])
            print_image(im)
            return
        case _:
            print("Outcome type %s not recognized" % outcome.type)
            return


def button_press():
    print('Button pressed!')
    outcome = outcome_generator.generate()
    outcome_handler(outcome)
    return True


def button_lambda_handler():
    return lambda: button_press()


# Button Functions
random_button.when_pressed = button_lambda_handler()

class CmdHandler:
    def __init__(self):
        self._run_cmd = True
        self._cmd_thread = Thread(target=self.start_cmd)
        self._cmd_thread.start()

    def terminate(self):
        self._run_cmd = False
        self._cmd_thread.join()

    def start_cmd(self):
        while self._run_cmd:
            code = input('Enter Type:')
            if code in ['image', 'joke', 'meme']:
                outcome = outcome_generator.generate(code)
                outcome_handler(outcome)
            else:
                print("Unknown Code " + code)
        return

if __name__ == '__main__':
    wait_for_internet_connection()
    print('--- Mememachine ---')
    pause()
