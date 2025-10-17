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

import requests
from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv
from escpos.printer import Usb
from gpiozero import Button
from openai import OpenAI
from usb.core import find as finddev

from outcome_interpreter import OutcomeGenerator

env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

# Globals
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), organization=os.getenv("OPENAI_ORG"))

# Button lock
button_busy = False

# Button
random_button = Button(23, bounce_time=0.05)

# POS Printer
dev = finddev(idVendor=0x04b8, idProduct=0x0202)
if dev is None:
    raise ValueError('Printer not found')
dev.reset()
time.sleep(2)
""" Seiko Epson Corp. Receipt Printer (EPSON TM-T88V) """
printer = Usb(0x04b8, 0x0202, profile="TM-T88V")

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
    image_width, image_height = image.size
    draw = ImageDraw.Draw(image)

    # Load a starting font
    base_font_path = "resources/arial.ttf"

    def get_font_for_text(text, max_width, start_size=80):
        # Find the largest font size that fits the image width.
        font_size = start_size
        font = ImageFont.truetype(base_font_path, font_size)
        text_width = draw.textlength(text, font=font)
        while text_width > max_width and font_size > 10:
            font_size -= 2
            font = ImageFont.truetype(base_font_path, font_size)
            text_width = draw.textlength(text, font=font)
        return font

    # Create fonts that fit the width (90% of image width)
    font_top = get_font_for_text(top_text, image_width * 0.9)
    font_bottom = get_font_for_text(bottom_text, image_width * 0.9)

    def draw_centered_text(text, y, font):
        lines = textwrap.wrap(text, width=40)
        for line in lines:
            line_width = draw.textlength(line, font=font)
            line_height = font.getbbox(line)[3]
            x = (image_width - line_width) / 2
            draw.text((x, y), line, font=font, fill='white',
                      stroke_width=2, stroke_fill='black')
            y += line_height
        return y

    # Top text
    y = int(image_height * 0.05)
    draw_centered_text(top_text, y, font_top)

    # Bottom text
    bottom_lines = textwrap.wrap(bottom_text, width=40)
    line_height = font_bottom.getbbox(bottom_text)[3]
    total_bottom_height = len(bottom_lines) * line_height
    y = image_height - total_bottom_height - int(image_height * 0.05)
    draw_centered_text(bottom_text, y, font_bottom)

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
        response = client.images.generate(prompt=prompt,
                                          n=1,
                                          size="512x512")
        image_url = response.data[0].url
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
        response = client.images.generate(prompt=prompt,
                                          n=1,
                                          size="512x512")
        image_url = response.data[0].url
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
            completion = client.chat.completions.create(model="gpt-3.5-turbo",
                                                        temperature=1,
                                                        max_tokens=60,
                                                        frequency_penalty=0,
                                                        presence_penalty=0,
                                                        messages=[
                                                            {"role": "system", "content": system_prompt},
                                                            {"role": "user", "content": prompt},
                                                        ])
            print(completion)
            text = completion.choices[0].message.content
        except Exception as e:
            print(f"Error on attempt {i + 1}: {e}")
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
            completion = client.chat.completions.create(model="gpt-3.5-turbo",
                                                        temperature=1,
                                                        max_tokens=60,
                                                        frequency_penalty=0,
                                                        presence_penalty=0,
                                                        messages=[
                                                            {"role": "system", "content": system_prompt},
                                                            {"role": "user", "content": prompt},
                                                        ])
            print(completion)
            text_json = json.loads(completion.choices[0].message.content)
        except Exception as e:
            print(f"Error on attempt {i + 1}: {e}")
            text_json = {"text_top": "Error", "text_bottom": "Error"}
            continue
        else:
            break
    print(text_json)
    return text_json


def outcome_handler(outcome):
    match outcome["type"]:
        case "joke":
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
            im_text = add_meme_text(im, meme_json['text_top'], meme_json['text_bottom'])
            print_image(im_text)
            return
        case _:
            print("Outcome type %s not recognized" % outcome["type"])
            return


def button_press():
    global button_busy
    if button_busy:
        print("Button press ignored, still busy...")
        return
    button_busy = True

    def handler():
        global button_busy
        try:
            print("Button pressed!")
            outcome = outcome_generator.generate("joke")
            print("Outcome:", outcome)
            outcome_handler(outcome)
        finally:
            button_busy = False

    # Run the actual work in a separate thread
    Thread(target=handler).start()


# Button
random_button.when_pressed = button_press


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
