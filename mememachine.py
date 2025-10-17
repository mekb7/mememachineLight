import json
import logging
import os
import shutil
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
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

# ----------------------
# Logger Setup
# ----------------------
LOG_FILE = '/mnt/data/logs/mememachine.log'


def setup_logger():
    logger = logging.getLogger("mememachine")
    logger.setLevel(logging.INFO)

    # File handler
    file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3)
    file_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(message)s'))
    logger.addHandler(console_handler)

    return logger


logger = setup_logger()

# ----------------------
# Load Environment
# ----------------------
load_dotenv(Path(__file__).resolve().parent / ".env")

# ----------------------
# Globals
# ----------------------
BUFFER_SIZE = 5
result_buffer = Queue(maxsize=BUFFER_SIZE)
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), organization=os.getenv("OPENAI_ORG"))


# ----------------------
# Printer Setup
# ----------------------
def init_printer():
    dev = finddev(idVendor=0x04b8, idProduct=0x0202)
    if dev is None:
        raise ValueError("Printer not found")
    dev.reset()
    time.sleep(1)
    return Usb(0x04b8, 0x0202, profile="TM-T88V")


printer = init_printer()

# ----------------------
# Outcome Generator
# ----------------------
with open("resources/template.json") as f:
    template_json = json.load(f)

outcome_generator = OutcomeGenerator(template_json)


# ----------------------
# Utilities
# ----------------------
def wait_for_internet_connection(url="https://google.com"):
    while True:
        try:
            urlopen(url, timeout=2)
            return
        except URLError:
            logger.warning("Waiting for internet...")
            time.sleep(1)


def safe_openai_call(call_func, retries=5, default=None):
    for attempt in range(1, retries + 1):
        try:
            return call_func()
        except Exception as e:
            logger.error(f"OpenAI call error on attempt {attempt}: {e}")
            last_exception = e
    return default


def fetch_image(url, save_dir="generated", prefix="image"):
    os.makedirs(save_dir, exist_ok=True)
    target_path = os.path.join(save_dir, f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg")
    res = requests.get(url, stream=True)
    if res.status_code == 200:
        with open(target_path, "wb") as f:
            shutil.copyfileobj(res.raw, f)
        return Image.open(target_path)
    else:
        logger.error(f"Failed to download image from {url}")
        return None


# ----------------------
# Meme Text Utilities
# ----------------------
def add_meme_text(image, top_text, bottom_text, font_path="resources/arial.ttf"):
    draw = ImageDraw.Draw(image)
    image_width, image_height = image.size

    def get_font(text, max_width, start_size=80):
        font_size = start_size
        font = ImageFont.truetype(font_path, font_size)
        while draw.textlength(text, font=font) > max_width and font_size > 10:
            font_size -= 2
            font = ImageFont.truetype(font_path, font_size)
        return font

    def draw_centered(text, y, font):
        for line in textwrap.wrap(text, width=40):
            line_width = draw.textlength(line, font=font)
            line_height = font.getbbox(line)[3]
            x = (image_width - line_width) / 2
            draw.text((x, y), line, font=font, fill="white", stroke_width=2, stroke_fill="black")
            y += line_height
        return y

    draw_centered(top_text, int(image_height * 0.05), get_font(top_text, image_width * 0.9))
    bottom_lines = textwrap.wrap(bottom_text, width=40)
    total_height = len(bottom_lines) * get_font(bottom_text, image_width * 0.9).getbbox(bottom_text)[3]
    draw_centered(bottom_text, image_height - total_height - int(image_height * 0.05),
                  get_font(bottom_text, image_width * 0.9))
    return image


# ----------------------
# OpenAI Handlers
# ----------------------
def get_text(prompt, system_prompt):
    return safe_openai_call(
        lambda: client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=1,
            max_tokens=60,
            frequency_penalty=0,
            presence_penalty=0,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": prompt}]
        ).choices[0].message.content,
        default="Error"
    )


def get_meme_json(prompt, system_prompt):
    return safe_openai_call(
        lambda: json.loads(client.chat.completions.create(
            model="gpt-3.5-turbo",
            temperature=1,
            max_tokens=60,
            frequency_penalty=0,
            presence_penalty=0,
            messages=[{"role": "system", "content": system_prompt},
                      {"role": "user", "content": prompt}]
        ).choices[0].message.content),
        default={"text_top": "Error", "text_bottom": "Error"}
    )


def generate_image(prompt):
    response = safe_openai_call(lambda: client.images.generate(prompt=prompt, n=1, size="512x512"))
    if response:
        return fetch_image(response.data[0].url)
    return None


# ----------------------
# Print Utilities
# ----------------------
def print_text(text):
    printer.text(text)
    printer.cut()


def print_image(image):
    printer.image(image, impl="graphics")
    printer.cut()


# ----------------------
# Outcome Handler
# ----------------------
def outcome_handler(outcome):
    type_handlers = {
        "joke": lambda: {"type": "joke", "text": get_text(outcome["promptRendered"], outcome["systemPromptRendered"])},
        "image": lambda: {"type": "image", "image": generate_image(outcome["promptRendered"])},
        "meme": lambda: meme_handler(outcome)
    }

    def meme_handler(outcome):
        meme_json = get_meme_json(outcome["promptRendered"], outcome["systemPromptRendered"])
        img = generate_image("Generate a meme image based on this top and bottom meme text: " + json.dumps(meme_json))
        return {"type": "meme", "image": add_meme_text(img, meme_json["text_top"], meme_json["text_bottom"])}

    result = type_handlers.get(outcome["type"], lambda: None)()
    if result is None:
        logger.warning(f"Unknown outcome type {outcome['type']}")
        return None

    return result


# ----------------------
# Prefill Buffer Thread (Parallelized)
# ----------------------
def prefill_worker():
    while True:
        if result_buffer.full():
            time.sleep(0.5)
            continue

        outcome = outcome_generator.generate(type="meme")
        result = outcome_handler(outcome)
        if result:
            result_buffer.put(result)
            logger.info(f"Buffer now at {result_buffer.qsize()}")


# Start multiple prefill workers to speed up buffer filling
NUM_WORKERS = 5  # You can increase if needed
executor = ThreadPoolExecutor(max_workers=NUM_WORKERS)
for _ in range(NUM_WORKERS):
    executor.submit(prefill_worker)

# ----------------------
# Button Handling
# ----------------------
button_busy = False
random_button = Button(23, bounce_time=0.05)


def button_press():
    global button_busy
    if button_busy:
        logger.info("Button press ignored, still busy...")
        return

    button_busy = True

    def handler():
        global button_busy
        try:
            try:
                result = result_buffer.get_nowait()
                logger.info(f"Buffer now at {result_buffer.qsize()}")
                logger.info("Using pre-generated result")
            except Empty:
                logger.warning("Buffer empty, generating live result")
                outcome = outcome_generator.generate(type="meme")
                result = outcome_handler(outcome)

            logger.info("Outputting " + result["type"])

            if result["type"] == "joke":
                print_text(result["text"])  # Text
            else:
                print_image(result["image"])  # Image and Meme both have an image
        finally:
            button_busy = False

    Thread(target=handler).start()


random_button.when_pressed = button_press


# ----------------------
# CLI Handler
# ----------------------
class CmdHandler:
    def __init__(self):
        self._run = True
        self._thread = Thread(target=self._start_cmd)
        self._thread.start()

    def terminate(self):
        self._run = False
        self._thread.join()

    def _start_cmd(self):
        while self._run:
            code = input("Enter Type:")
            if code in ["image", "joke", "meme"]:
                outcome = outcome_generator.generate(code)
                outcome_handler(outcome)
            else:
                logger.warning(f"Unknown Code {code}")


# ----------------------
# Main
# ----------------------
if __name__ == "__main__":
    wait_for_internet_connection()
    logger.info("--- Mememachine ---")
    pause()
