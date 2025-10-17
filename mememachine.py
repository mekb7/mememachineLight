import json
import logging
import os
import shutil
import sys
import textwrap
import time
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from queue import Queue, Empty
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

# Logger
log_file = '/mnt/data/logs/mememachine.log'

file_handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
file_handler.setLevel(logging.INFO)

file_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
file_handler.setFormatter(file_formatter)

console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

console_formatter = logging.Formatter(
    '%(asctime)s [%(levelname)s] %(message)s'
)
console_handler.setFormatter(console_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)

logger = logging.getLogger(__name__)

# .env
env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(dotenv_path=env_path)

# Buffer
BUFFER_SIZE = 5
result_buffer = Queue(maxsize=BUFFER_SIZE)

# Globals
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), organization=os.getenv("OPENAI_ORG"))

# Button
random_button = Button(23, bounce_time=0.05)
button_busy = False

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
            logger.warning("Waiting for internet...")
            time.sleep(1)
            pass


def add_meme_text(image, top_text, bottom_text):
    image_width, image_height = image.size
    draw = ImageDraw.Draw(image)

    base_font_path = "resources/arial.ttf"

    def get_font_for_text(text, max_width, start_size=80):
        font_size = start_size
        font = ImageFont.truetype(base_font_path, font_size)
        text_width = draw.textlength(text, font=font)
        while text_width > max_width and font_size > 10:
            font_size -= 2
            font = ImageFont.truetype(base_font_path, font_size)
            text_width = draw.textlength(text, font=font)
        return font

    # 90% of image width
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
            logger.error('Image Couldn\'t be retrieved')
    except Exception as e:
        logger.error(e)


def print_for_prompt(prompt):
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
            logger.error('Image couldn\'t be retrieved')
    except Exception as e:
        logger.error(e)


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
            text = completion.choices[0].message.content
        except Exception as e:
            logger.error(f"Error on attempt {i + 1}: {e}")
            text = "Error"
            continue
        else:
            break
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
            text_json = json.loads(completion.choices[0].message.content)
        except Exception as e:
            logger.error(f"Error on attempt {i + 1}: {e}")
            text_json = {"text_top": "Error", "text_bottom": "Error"}
            continue
        else:
            break
    return text_json


def outcome_handler(outcome, return_result=False):
    if outcome["type"] == "joke":
        text = get_text_for_prompt(outcome["systemPromptRendered"], outcome["promptRendered"])
        if return_result:
            return {"type": "joke", "text": text}
        print_text(text)
        return None
    elif outcome["type"] == "image":
        img = get_image_for_prompt(outcome["promptRendered"])
        if return_result:
            return {"type": "image", "image": img}
        print_image(img)
        return None
    elif outcome["type"] == "meme":
        img = get_image_for_prompt(outcome["promptRendered"])
        meme_json = get_meme_text_for_prompt(outcome["systemPromptRendered"], outcome["promptRendered"])
        img_text = add_meme_text(img, meme_json['text_top'], meme_json['text_bottom'])
        if return_result:
            return {"type": "meme", "image": img_text}
        print_image(img_text)
        return None
    else:
        logger.warning(f"Unknown outcome type {outcome['type']}")
        return None

def prefill_buffer():
    while True:
        if not result_buffer.full():
            try:
                # Generate an outcome
                outcome = outcome_generator.generate()

                # Pre-generate the OpenAI data depending on type
                if outcome["type"] == "joke":
                    text = get_text_for_prompt(outcome["systemPromptRendered"], outcome["promptRendered"])
                    result_buffer.put({"type": "joke", "text": text})
                elif outcome["type"] == "image":
                    img = get_image_for_prompt(outcome["promptRendered"])
                    result_buffer.put({"type": "image", "image": img})
                elif outcome["type"] == "meme":
                    img = get_image_for_prompt(outcome["promptRendered"])
                    meme_json = get_meme_text_for_prompt(outcome["systemPromptRendered"], outcome["promptRendered"])
                    img_text = add_meme_text(img, meme_json['text_top'], meme_json['text_bottom'])
                    result_buffer.put({"type": "meme", "image": img_text})
                else:
                    logger.warning(f"Unknown outcome type {outcome['type']}")
            except Exception as e:
                logger.error(f"Error generating prefill result: {e}")
        else:
            time.sleep(0.5)  # Wait a bit if buffer is full

def button_press():
    global button_busy
    if button_busy:
        logger.info("Button press ignored, still busy...")
        return
    button_busy = True

    def handler():
        global button_busy
        try:
            logger.info("Button pressed!")
            try:
                # Get a pre-generated result
                result = result_buffer.get_nowait()
                logger.info("Using pre-generated result")
            except Empty:
                logger.warning("Buffer empty, generating live result")
                outcome = outcome_generator.generate()
                result = outcome_handler(outcome, return_result=True)

            # Display the result
            if result["type"] == "joke":
                print_text(result["text"])
            elif result["type"] in ["image", "meme"]:
                print_image(result["image"])

        finally:
            button_busy = False

    Thread(target=handler).start()

# Button
random_button.when_pressed = button_press

# Start the prefill thread
Thread(target=prefill_buffer, daemon=True).start()

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
                logger.warning("Unknown Code " + code)
        return


if __name__ == '__main__':
    wait_for_internet_connection()
    logger.info('--- Mememachine ---')
    pause()
