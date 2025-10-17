import time

from escpos.printer import Usb
from usb.core import find as finddev

# POS Printer
dev = finddev(idVendor=0x04b8, idProduct=0x0202)
if dev is None:
    raise ValueError('Printer not found')
dev.reset()
time.sleep(2)
""" Seiko Epson Corp. Receipt Printer (EPSON TM-T88V) """
printer = Usb(0x04b8, 0x0202)
printer.text("TEST")
printer.cut()
