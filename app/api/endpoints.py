import os
import io
import json
import tempfile
import zipfile
import subprocess
import csv
import base64
from datetime import datetime

from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Response, Query
from fastapi.responses import JSONResponse
import pandas as pd
import docx
import openpyxl
from fpdf import FPDF
from PIL import Image
import pymupdf as fitz # Warning fixed
from pdf2docx import Converter
from groq import AsyncGroq # Groq Library

# Enterprise Config
from app.config import settings

from app.services.image_resizer import resize_and_compress_image, PRESETS
from app.services.krutidev_translexer import convert_krutidev_to_unicode, bilingual_search, highlight_matches
from app.services.converter import pdf_to_text_and_json, text_to_docx
from app.services.astrabot import (
    MAX_IMAGE_BYTES, AstraBotError, InvalidImageError, OllamaUnavailableError, process_image_with_pure_ai,
)
from app.services.auth import get_optional_user, record_usage

router = APIRouter()

# ==========================================
# HELPER: ENTERPRISE OFFICE TO PDF
# ==========================================
def convert_office_to_pdf(input_bytes: bytes, ext: str) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        input_path = os.path.join(temp_dir, f"input.{ext}")
        with open(input_path, "wb") as f:
            f.write(input_bytes)
        
        libreoffice_path = "soffice" 
        if os.name == 'nt': 
            possible_path = r"C:\Program Files\LibreOffice\program\soffice.exe"
            if os.path.exists(possible_path):
                libreoffice_path = possible_path

        cmd = [libreoffice_path, '--headless', '--convert-to', 'pdf', '--outdir', temp_dir, input_path]
        
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        except subprocess.CalledProcessError:
            raise HTTPException(status_code=500, detail="LibreOffice conversion failed. Is it installed?")
        
        output_path = os.path.join(temp_dir, "input.pdf")
        if not os.path.exists(output_path):
            raise HTTPException(status_code=500, detail="PDF generation failed.")
            
        with open(output_path, "rb") as f:
            return f.read()

# ==========================================
# HELPER: GET ALL AVAILABLE GROQ KEYS
# ==========================================
def get_groq_keys():
    keys = []
    try:
        primary = settings.GROQ_API_KEY.get_secret_value()
        if primary: keys.append(primary)
    except Exception: pass
    
    try:
        backup = settings.GROQ_API_KEY_BACKUP.get_secret_value()
        if backup: keys.append(backup)
    except Exception: pass
    
    return keys

# ==========================================
# 1. BASE TOOLS (Resizer, Search, AstraBot)
# ==========================================

@router.get("/presets")
async def get_presets():
    return {"status": "success", "presets": PRESETS}

@router.post("/resize-photo")
async def resize_photo(
    file: UploadFile = File(...),
    preset: str = Form(None),
    target_kb: int = Form(35),
    candidate_name: str = Form(None),
    dop: str = Form(None),
    dpi: int = Form(200),
    user: dict | None = Depends(get_optional_user),
):
    contents = await file.read()
    output_bytes = resize_and_compress_image(
        image_bytes=contents, target_kb=target_kb, preset=preset,
        candidate_name=candidate_name, dop=dop, dpi=dpi
    )
    await record_usage(user, "photo_resize", f"Preset: {preset or 'custom'}; target: {target_kb} KB")
    return Response(content=output_bytes, media_type="image/jpeg", headers={"Content-Disposition": f"attachment; filename=resized_{file.filename}.jpg"})

@router.post("/search-pdf")
async def search_pdf(file: UploadFile = File(...), query: str = Form(...), user: dict | None = Depends(get_optional_user)):
    contents = await file.read()
    data = pdf_to_text_and_json(contents)
    results = []
    for page_data in data["pages"]:
        page_text = page_data["text"]
        match_found, positions = bilingual_search(page_text, query)
        highlighted_text = highlight_matches(page_text, query)
        results.append({
            "page_number": page_data["page_number"], "total_words": page_data["word_count"], "match_found": match_found,
            "matching_positions": positions[:10], "highlighted_text": highlighted_text[:500] + ("..." if len(highlighted_text) > 500 else ""), "text_length": len(page_text)
        })
    full_text = data["full_text"]
    match_found_full, positions_full = bilingual_search(full_text, query)
    highlighted_full = highlight_matches(full_text, query)
    await record_usage(user, "pdf_search", f"Searched for: {query} across {data['total_pages']} pages")
    return {
        "total_pages": data["total_pages"], "query": query, "match_found_overall": match_found_full,
        "total_matches": len(positions_full), "page_results": results, "highlighted_full_text": highlighted_full[:1000] + ("..." if len(highlighted_full) > 1000 else "")
    }

@router.post("/astrabot/execute")
async def execute_astrabot(
    command: str = Form(...), 
    file: UploadFile = File(None), 
    candidate_name: str | None = Form(None), 
    user: dict | None = Depends(get_optional_user)
):
    if file is None: raise HTTPException(status_code=400, detail="Please select a file first.")
    if not command.strip(): raise HTTPException(status_code=400, detail="Please enter an instruction.")
    if len(command) > 2000: raise HTTPException(status_code=400, detail="Instruction too long.")
    if candidate_name and len(candidate_name) > 200: raise HTTPException(status_code=400, detail="Candidate name too long.")

    file_contents = await file.read()
    if len(file_contents) > MAX_IMAGE_BYTES: raise HTTPException(status_code=413, detail="File is too large. Max: 12 MB.")

    try:
        processed_bytes, reply_message = await process_image_with_pure_ai(
            prompt=command, 
            file_bytes=file_contents, 
            filename=file.filename or "file",
            candidate_name=candidate_name
        )
    except InvalidImageError as exc: raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OllamaUnavailableError as exc: raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AstraBotError as exc: raise HTTPException(status_code=502, detail=str(exc)) from exc

    await record_usage(user, "astrabot", "Processed a file instruction")
    
    file_base64 = None
    if processed_bytes is not None:
        b64_str = base64.b64encode(processed_bytes).decode("ascii")
        file_base64 = f"data:image/jpeg;base64,{b64_str}"
        
    original_name = file.filename or "file"
    safe_stem = original_name.rsplit(".", 1)[0].replace("/", "_").replace("\\", "_")
    
    return {
        "status": "success", 
        "bot_reply": reply_message, 
        "download_file": file_base64, 
        "filename": f"ai_processed_{safe_stem}.jpg"
    }

# ==========================================
# 2. AI DOCUMENT SUMMARIZER (DUAL KEY FALLBACK)
# ==========================================
@router.post("/summarize-document")
async def summarize_document(file: UploadFile = File(...), user: dict | None = Depends(get_optional_user)):
    content = await file.read()
    data = pdf_to_text_and_json(content)
    full_text = data["full_text"]
    
    if not full_text.strip():
        raise HTTPException(status_code=400, detail="Could not extract text from this document.")

    text_to_summarize = full_text[:30000]
    prompt = f"""
    You are an expert exam document summarizer. Read the following text and create a highly structured summary.
    Provide the output in the following format:
    1. Overview (English)
    2. Overview (Hindi)
    3. Key Milestones / Dates (Bullet points)
    4. Important Rules / Legal Provisions (Bullet points)
    
    Text to summarize:
    {text_to_summarize}
    """

    summary_output = ""
    method_used = ""
    ai_error_message = None

    # SMART FALLBACK: Primary -> Backup
    groq_keys = get_groq_keys()
    
    if not groq_keys:
        method_used = "Smart Extractor (Fallback)"
    else:
        for groq_key in groq_keys:
            try:
                client = AsyncGroq(api_key=groq_key)
                chat_completion = await client.chat.completions.create(
                    messages=[{"role": "user", "content": prompt}],
                    model="openai/gpt-oss-120b", # Active Model
                    temperature=0.3,
                    max_tokens=4000
                )
                summary_output = chat_completion.choices[0].message.content
                method_used = "AI (Groq GPT-OSS 120B)"
                break # Success! Break loop
            except Exception as key_error:
                ai_error_message = key_error
                continue # Try next key

    # If all keys failed or empty
    if not summary_output:
        print(f"All Groq Keys Failed. Last error: {ai_error_message}")
        method_used = "Smart Extractor (Fallback)"
        
        dates, articles = [], []
        for l in full_text.splitlines():
            if any(w in l.lower() for w in ["article", "anuched", "adhiniyam", "act", "section"]): articles.append(l.strip())
            if any(w in l.lower() for w in ["19", "20", "date", "tarikh"]):
                if len(l.strip()) < 80: dates.append(l.strip())
                
        summary_output = "⚠️ Note: AI model is offline. Using Fallback.\n\n📅 KEY MILESTONES / DATES:\n"
        summary_output += "".join([f"- {d}\n" for d in dates[:10]]) if dates else "- No specific dates found.\n"
        summary_output += "\n📜 LEGAL ARTICLES & PROVISIONS:\n"
        summary_output += "".join([f"- {a}\n" for a in articles[:10]]) if articles else "- No articles found.\n"
        summary_output += f"\n📝 NOTES:\nKagazAstra ne kul {data['total_pages']} prishth scan kiye."

    await record_usage(user, "document_summary", f"Summarized {data['total_pages']} pages using {method_used}")
    return {"status": "success", "total_pages_read": data["total_pages"], "method_used": method_used, "ai_summary": summary_output}


# ==========================================
# 3. ENTERPRISE CONVERSION ENDPOINTS
# ==========================================
@router.post("/convert/office-to-pdf")
async def office_to_pdf(file: UploadFile = File(...), user: dict | None = Depends(get_optional_user)):
    ext = file.filename.split('.')[-1].lower()
    contents = await file.read()
    try:
        pdf_bytes = convert_office_to_pdf(contents, ext)
        await record_usage(user, f"{ext}_to_pdf", file.filename)
        return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{file.filename}.pdf"'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/convert/pdf-to-docx")
async def pdf_to_docx_pro(file: UploadFile = File(...), user: dict | None = Depends(get_optional_user)):
    contents = await file.read()
    with tempfile.TemporaryDirectory() as temp_dir:
        pdf_path = os.path.join(temp_dir, "input.pdf")
        docx_path = os.path.join(temp_dir, "output.docx")
        with open(pdf_path, "wb") as f: f.write(contents)
        try:
            cv = Converter(pdf_path)
            cv.convert(docx_path, start=0, end=None)
            cv.close()
            with open(docx_path, "rb") as f: docx_bytes = f.read()
            await record_usage(user, "pdf_to_docx", file.filename)
            return Response(content=docx_bytes, media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="converted.docx"'})
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

@router.post("/convert/pdf-to-jpg")
async def pdf_to_jpg(file: UploadFile = File(...), user: dict | None = Depends(get_optional_user)):
    contents = await file.read()
    try:
        doc = fitz.open(stream=contents, filetype="pdf")
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for page_num in range(len(doc)):
                pix = doc.load_page(page_num).get_pixmap(dpi=150)
                zip_file.writestr(f"page_{page_num + 1}.jpg", pix.tobytes("jpeg"))
        zip_buffer.seek(0)
        await record_usage(user, "pdf_to_jpg", file.filename)
        return Response(content=zip_buffer.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="pdf_images.zip"'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/convert/xlsx-to-csv")
async def xlsx_to_csv(file: UploadFile = File(...), user: dict | None = Depends(get_optional_user)):
    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
        csv_data = df.to_csv(index=False).encode('utf-8')
        await record_usage(user, "xlsx_to_csv", file.filename)
        return Response(content=csv_data, media_type="text/csv", headers={"Content-Disposition": f'attachment; filename="converted.csv"'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/convert/csv-to-xlsx")
async def csv_to_xlsx(file: UploadFile = File(...), user: dict | None = Depends(get_optional_user)):
    contents = await file.read()
    try:
        df = pd.read_csv(io.BytesIO(contents))
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine='openpyxl')
        buf.seek(0)
        await record_usage(user, "csv_to_xlsx", file.filename)
        return Response(content=buf.read(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="converted.xlsx"'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/convert/image-to-format")
async def image_to_format(target_format: str = Query(...), file: UploadFile = File(...), user: dict | None = Depends(get_optional_user)):
    contents = await file.read()
    target_format = target_format.lower()
    try:
        img = Image.open(io.BytesIO(contents))
        buf = io.BytesIO()
        if target_format == 'pdf':
            img.convert("RGB").save(buf, format="PDF"); media_type = "application/pdf"
        elif target_format in ['jpg', 'jpeg']:
            img.convert("RGB").save(buf, format="JPEG", quality=90); media_type = "image/jpeg"
        elif target_format == 'png':
            img.save(buf, format="PNG"); media_type = "image/png"
        elif target_format == 'webp':
            img.convert("RGB").save(buf, format="WEBP", quality=80); media_type = "image/webp"
        else:
            raise HTTPException(status_code=400, detail="Unsupported image format")
        buf.seek(0)
        await record_usage(user, f"image_to_{target_format}", file.filename)
        return Response(content=buf.read(), media_type=media_type, headers={"Content-Disposition": f'attachment; filename="converted.{target_format}"'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/convert/image-to-text")
async def convert_image_to_text(file: UploadFile = File(...), user: dict | None = Depends(get_optional_user)):
    import pytesseract
    contents = await file.read()
    try:
        img = Image.open(io.BytesIO(contents))
        text = pytesseract.image_to_string(img, lang="eng+hin")
        await record_usage(user, "image_to_text", file.filename)
        return Response(content=text.encode("utf-8"), media_type="text/plain", headers={"Content-Disposition": f'attachment; filename="ocr_result.txt"'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/convert/txt-to-pdf")
async def txt_to_pdf(file: UploadFile = File(...), user: dict | None = Depends(get_optional_user)):
    contents = await file.read()
    try:
        text = contents.decode('utf-8')
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for line in text.split('\n'):
            pdf.cell(200, 10, txt=line, ln=1, align='L')
        pdf_out = pdf.output(dest='S').encode('latin-1')
        await record_usage(user, "txt_to_pdf", file.filename)
        return Response(content=pdf_out, media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="converted.pdf"'})
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))