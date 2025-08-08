import easyocr
import spacy
import fitz  # PyMuPDF for PDF handling
import re
from fpdf import FPDF
import gradio as gr
import os
import subprocess
import sys
# Check and install model
try:
    nlp = spacy.load("en_core_web_sm")
except OSError:
    subprocess.check_call([sys.executable, "-m", "spacy", "download", "en_core_web_sm"])
    nlp = spacy.load("en_core_web_sm")

# Initialize EasyOCR (English language)
reader = easyocr.Reader(['en'])  # Use CPU (-1)

# Initialize SpaCy model for NER (Named Entity Recognition)
nlp = spacy.load("en_core_web_sm")

# Regex patterns for sensitive information
ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"  # Social Security Number pattern
credit_card_pattern = r"\b(?:\d{4}[- ]?){3}\d{4}\b"  # Credit card pattern

# Function to convert PDF pages to images
def pdf_to_images(pdf_file):
    doc = fitz.open(stream=pdf_file.read(), filetype="pdf")
    images = []
    for page_num in range(doc.page_count):  # Loop through all pages
        page = doc.load_page(page_num)  # Load each page
        pix = page.get_pixmap()  # Convert page to image (pixmap)
        img = pix.tobytes("ppm")  # Convert to ppm image bytes
        images.append(img)  # Append image to list
    return images

# Function to extract text from images using EasyOCR
def ocr_from_images(images):
    results = []
    for img in images:
        result = reader.readtext(img)  # Run OCR on the image
        extracted_text = " ".join([text[1] for text in result])  # Extract text (ignoring bounding box and confidence score)
        results.append(extracted_text)
    return "\n".join(results)

# Function to process and redact sensitive information using NER and regex
def redact_sensitive_information(text):
    # Process text with SpaCy NER
    doc = nlp(text)
    
    # Redact NER entities (like names, addresses, etc.)
    redacted_text = text
    for ent in doc.ents:
        if ent.label_ in ["PERSON", "GPE", "ORG"]:
            redacted_text = redacted_text.replace(ent.text, "[REDACTED]")
    
    # Redact social security numbers (SSNs) using regex
    redacted_text = re.sub(ssn_pattern, "[REDACTED SSN]", redacted_text)
    
    # Redact credit card numbers using regex
    redacted_text = re.sub(credit_card_pattern, "[REDACTED CREDIT CARD]", redacted_text)

    return redacted_text

# Function to handle the entire document processing
def process_pdf(pdf_file):
    images = pdf_to_images(pdf_file)  # Convert PDF to images
    extracted_text = ocr_from_images(images)  # Extract text from images using EasyOCR
    redacted_text = redact_sensitive_information(extracted_text)  # Redact sensitive info

    # Export the redacted text to PDF and Word
    output_pdf = "/mnt/data/redacted_output.pdf"
    output_word = "/mnt/data/redacted_output.docx"
    
    # Export to PDF and Word
    export_to_pdf(redacted_text, output_pdf)
    export_to_word(redacted_text, output_word)
    
    return redacted_text, output_pdf, output_word

# Function to export redacted text to PDF
def export_to_pdf(redacted_text, output_pdf_path):
    # Create PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Set font
    pdf.set_font("Arial", size=12)

    # Add text
    pdf.multi_cell(0, 10, redacted_text)

    # Save the redacted PDF
    pdf.output(output_pdf_path)
    return output_pdf_path

# Function to export redacted text to Word
from docx import Document
def export_to_word(redacted_text, output_word_path):
    # Create a Word document
    doc = Document()
    doc.add_paragraph(redacted_text)
    
    # Save the redacted Word document
    doc.save(output_word_path)
    return output_word_path

# Gradio interface
interface = gr.Interface(
    fn=process_pdf,  # Function to process the PDF and extract/redact text
    inputs=gr.File(label="Upload PDF"),  # File input for PDF upload
    outputs=[
        gr.Textbox(label="Redacted Text"),  # Display the redacted text
        gr.File(label="Download Redacted PDF"),  # Allow users to download redacted PDF
        gr.File(label="Download Redacted Word Document")  # Allow users to download redacted Word doc
    ],
    live=True
)

# Launch the Gradio interface
interface.launch()





