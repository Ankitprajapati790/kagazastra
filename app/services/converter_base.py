from typing import Dict

from typing import Dict

class ConversionResult:
    """Standardized conversion result"""
    def __init__(self, success: bool, output_data: bytes = None,
                 output_name: str = "", error: str = None,
                 metadata: Dict = None):
        self.success = success
        self.output_data = output_data
        self.output_name = output_name
        self.error = error
        self.metadata = metadata or {}


# PDF Converters
def pdf_to_word(pdf_bytes: bytes) -> ConversionResult:
    """PDF → DOCX using pdf2docx"""
    try:
        from pdf2docx import Converter
        import tempfile
        import os
        
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tmp_pdf:
            tmp_pdf.write(pdf_bytes)
            tmp_pdf_path = tmp_pdf.name
        
        docx_path = tmp_pdf_path.replace('.pdf', '.docx')
        with open(tmp_pdf_path, 'rb') as pdf_file, \
             open(docx_path, 'wb') as docx_file:
            cv = Converter(pdf_file)
            cv.convert(docx_file, start=0, end=None)
            cv.close()
        
        with open(docx_path, 'rb') as f:
            output_data = f.read()
        
        # Cleanup
        os.unlink(tmp_pdf_path)
        if os.path.exists(docx_path):
            os.unlink(docx_path)
        
        return ConversionResult(True, output_data, 
                              output_name="converted.docx",
                              metadata={"format": "docx"})
    except ImportError:
        return ConversionResult(False, error="pdf2docx not installed")
    except Exception as e:
        return ConversionResult(False, error=str(e))


def pdf_to_text(pdf_bytes: bytes) -> ConversionResult:
    """PDF → TXT (extract all text)"""
    try:
        from pypdf import PdfReader
        import io
        
        reader = PdfReader(io.BytesIO(pdf_bytes))
        text_parts = []
        
        for page in reader.pages:
            text = page.extract_text()
            if text:
                text_parts.append(text)
        
        full_text = "\n\n".join(text_parts)
        
        return ConversionResult(True, full_text.encode('utf-8'),
                              output_name="extracted.txt",
                              metadata={"pages": len(reader.pages),
                                        "chars": len(full_text)})
    except ImportError:
        return ConversionResult(False, error="pypdf not installed")
    except Exception as e:
        return ConversionResult(False, error=str(e))


def image_from_pdf(pdf_bytes: bytes, format: str = "JPG", dpi: int = 200) -> ConversionResult:
    """PDF → Image (first page only - placeholder)"""
    # Note: pypdf alone can't render images
    # Real implementation needs PyMuPDF or similar
    return ConversionResult(False, error="PDF rendering needs PyMuPDF")