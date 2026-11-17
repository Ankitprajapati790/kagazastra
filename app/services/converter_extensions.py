# Converter Extensions for KagazAstra
# Comprehensive document conversion module

import io
import os
import subprocess
from typing import Optional

import openpyxl
from PIL import Image
from pypdf import PdfReader, PdfWriter
import docx

pytesseract = None
TesseractNotFoundError = None
EasyOCRReader = None
PdfImagePlugin = None

def _init_ocr_dependencies():
    global pytesseract, TesseractNotFoundError, EasyOCRReader, PdfImagePlugin
    try:
        import pytesseract
        from pytesseract import TesseractNotFoundError as TesseractNotFoundError
        pytesseract = pytesseract
    except ImportError:
        pass
    try:
        from PIL import PdfImagePlugin as PdfImagePlugin
    except ImportError:
        pass
    try:
        import easyocr
        EasyOCRReader = easyocr
    except ImportError:
        pass

import os
import subprocess
from typing import Optional

import openpyxl
from PIL import Image
from pypdf import PdfReader, PdfWriter
import docx

pytesseract = None
TesseractNotFoundError = None
EasyOCRReader = None
PdfImagePlugin = None

def _init_ocr_dependencies():
    global pytesseract, TesseractNotFoundError, EasyOCRReader, PdfImagePlugin
    try:
        import pytesseract
        from pytesseract import TesseractNotFoundError as TesseractNotFoundError
        pytesseract = pytesseract
    except ImportError:
        pass
    try:
        from PIL import PdfImagePlugin as PdfImagePlugin
    except ImportError:
        pass
    try:
        import easyocr
        EasyOCRReader = easyocr
    except ImportError:
        pass

