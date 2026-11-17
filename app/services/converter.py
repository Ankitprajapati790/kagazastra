import io
from pypdf import PdfReader, PdfWriter
import docx

def pdf_to_text_and_json(pdf_bytes: bytes) -> dict:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    pages_data = []
    full_text = []
    
    for idx, page in enumerate(reader.pages):
        text = page.extract_text() or ""
        pages_data.append({
            "page_number": idx + 1,
            "text": text,
            "word_count": len(text.split())
        })
        full_text.append(text)
        
    return {
        "total_pages": len(reader.pages),
        "full_text": "\n".join(full_text),
        "pages": pages_data
    }

def text_to_docx(text: str) -> bytes:
    doc = docx.Document()
    for line in text.split("\n"):
        doc.add_paragraph(line)
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()
