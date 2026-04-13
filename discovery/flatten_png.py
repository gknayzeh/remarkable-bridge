#!/usr/bin/env python3
"""Flatten RGBA PNG to RGB with white background. Usage: flatten_png.py <file.png>"""
import sys
from PIL import Image

path = sys.argv[1]
img = Image.open(path)
if img.mode == "RGBA":
    bg = Image.new("RGB", img.size, (255, 255, 255))
    bg.paste(img, mask=img.split()[3])
    bg.save(path)
