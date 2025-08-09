import easyocr
import fitz  # PyMuPDF for PDF handling
import re
import tempfile
from fpdf import FPDF
import streamlit as st
import os
from transformers import pipeline
from docx import Document

# Optional: Load NER model for more sophisticated address detection (commented out for now)
# ner_model = pipeline("ner", model="dbmdz/bert-large-cased-finetuned-conll03-english")

# Initialize EasyOCR (English language)
reader = easyocr.Reader(['en'])  # Use CPU (-1)

# Enhanced regex patterns that account for OCR errors
ssn_patterns = [
    r"\b\d{3}[-\s<>]\d{2}[-\s<>]\d{4}\b",  # Handles OCR errors like < > instead of -
    r"\b\d{3}\s*\d{2}\s*\d{4}\b"  # More flexible spacing
]

credit_card_patterns = [
    r"\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b",  # Standard 4-4-4-4 format
    r"\b\d{4}[\s\-]\d{4}[\s\-]\d{3}[A-Za-z0-9][\s\-][A-Za-z0-9]\d{3}\b"  # Handles OCR errors in last groups
]

# More precise address patterns to avoid false positives
address_patterns = [
    r"\b\d{1,5}\s+[A-Za-z]+\s+(?:[A-Za-z]+\s+)?(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd|Way|Court|Ct|Place|Pl|Circle|Cir)\b",
    r"\b\d{5}(?:[-\s]\d{4})?\b"  # ZIP codes only (5 digits or 5-4 format)
]

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

# Function to clean OCR text and improve accuracy
def clean_ocr_text(text):
    """Clean common OCR errors before processing"""
    # Dictionary of common OCR character substitutions
    ocr_corrections = {
        '0': ['O', 'o', '°'],
        '1': ['l', 'I', '|'],
        '5': ['S', 's'],
        '6': ['G', 'b'],
        '8': ['B'],
        'S': ['5'],
        'O': ['0'],
        'I': ['1', 'l'],
        '<': ['-'],
        '>': ['-'],
    }
    
    cleaned_text = text
    # Apply corrections (be careful not to over-correct)
    for correct, errors in ocr_corrections.items():
        for error in errors:
            # Only replace in specific contexts (like potential SSN/CC patterns)
            pass  # We'll be more conservative here
    
    return cleaned_text

# Enhanced function to detect sensitive patterns with OCR error tolerance
def detect_and_redact_patterns(text):
    """More sophisticated pattern detection that handles OCR errors"""
    redacted_text = text
    
    # SSN Detection with OCR error tolerance
    # Look for patterns like XXX-XX-XXXX but allow some OCR errors
    import re
    
    # Find potential SSN patterns (even with OCR errors)
    potential_ssns = re.finditer(r'\b\d{3}[-\s<>o]\d{2}[-\s<>o]\d{4}\b', text, re.IGNORECASE)
    for match in potential_ssns:
        redacted_text = redacted_text.replace(match.group(), '[REDACTED SSN]')
    
    # Find potential credit card patterns
    potential_ccs = re.finditer(r'\b\d{4}[\s\-]\d{4}[\s\-]\d{3}[A-Za-z0-9][\s\-][A-Za-z0-9]\d{2,3}\b', text)
    for match in potential_ccs:
        redacted_text = redacted_text.replace(match.group(), '[REDACTED CREDIT CARD]')
    
    # Standard credit card patterns
    potential_ccs_standard = re.finditer(r'\b\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b', text)
    for match in potential_ccs_standard:
        redacted_text = redacted_text.replace(match.group(), '[REDACTED CREDIT CARD]')
    
    # Address patterns - be more conservative
    # Only redact clear address patterns
    address_matches = re.finditer(r'\b\d{1,4}\s+[A-Za-z]+\s+(?:Street|St|Avenue|Ave|Road|Rd|Drive|Dr|Lane|Ln|Boulevard|Blvd)\b', text, re.IGNORECASE)
    for match in address_matches:
        redacted_text = redacted_text.replace(match.group(), '[REDACTED ADDRESS]')
    
    # ZIP codes (5 digits, but not standalone numbers that might be something else)
    zip_matches = re.finditer(r'\b\d{5}(?:-\d{4})?\b', text)
    for match in zip_matches:
        # Additional context check - only redact if it looks like a ZIP
        context = text[max(0, match.start()-10):match.end()+10].lower()
        if any(indicator in context for indicator in ['zip', 'postal', 'address', 'mail']):
            redacted_text = redacted_text.replace(match.group(), '[REDACTED ZIP]')
    
    return redacted_text

# SIMPLE CONSERVATIVE APPROACH - only redacts very obvious patterns
def redact_sensitive_information_simple(text):
    """
    Very conservative redaction - only redacts very obvious patterns
    Use this function if you want minimal false positives
    """
    redacted_text = text
    
    # Only redact very clear SSN patterns
    redacted_text = re.sub(r'\bSSN:\s*\d{3}[-\s<>]\d{2}[-\s<>]\d{4}\b', '[REDACTED SSN]', redacted_text, flags=re.IGNORECASE)
    redacted_text = re.sub(r'\bSocial Security:\s*\d{3}[-\s<>]\d{2}[-\s<>]\d{4}\b', '[REDACTED SSN]', redacted_text, flags=re.IGNORECASE)
    
    # Only redact when explicitly labeled as credit card
    redacted_text = re.sub(r'\bCredit Card:\s*\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b', '[REDACTED CREDIT CARD]', redacted_text, flags=re.IGNORECASE)
    redacted_text = re.sub(r'\bCard Number:\s*\d{4}[\s\-]\d{4}[\s\-]\d{4}[\s\-]\d{4}\b', '[REDACTED CREDIT CARD]', redacted_text, flags=re.IGNORECASE)
    
    # Only redact when explicitly labeled as address
    redacted_text = re.sub(r'\bAddress:\s*[^\n]+', '[REDACTED ADDRESS]', redacted_text, flags=re.IGNORECASE)
    redacted_text = re.sub(r'\bZIP:\s*\d{5}(?:-\d{4})?\b', '[REDACTED ZIP]', redacted_text, flags=re.IGNORECASE)
    
    return redacted_text

# Main redaction function - you can switch between different approaches
def redact_sensitive_information(text):
    """
    Main redaction function. 
    Switch between different approaches based on your needs:
    1. redact_sensitive_information_simple - Very conservative, only labeled data
    2. detect_and_redact_patterns - More aggressive pattern matching
    """
    
    # Choose your approach:
    return redact_sensitive_information_simple(text)  # Very conservative
    # return detect_and_redact_patterns(text)  # More comprehensive

# Function to export redacted text to PDF
def export_to_pdf(redacted_text):
    print(f"Redacted Text: {redacted_text[:100]}...") 
    # Create a temporary file for PDF
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmpfile:
        tmpfile.close()  # Close the file to ensure it's saved to disk
        output_pdf_path = tmpfile.name  # Get the path of the temporary file

    # Create PDF
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    # Set font
    pdf.set_font("Arial", size=12)

    # Add text to the PDF (handle encoding issues)
    try:
        pdf.multi_cell(0, 10, redacted_text.encode('latin-1', 'replace').decode('latin-1'))
    except:
        # Fallback for special characters
        cleaned_text = ''.join(char if ord(char) < 128 else '?' for char in redacted_text)
        pdf.multi_cell(0, 10, cleaned_text)

    # Save the redacted PDF to the temporary file path
    pdf.output(output_pdf_path)
    
    return output_pdf_path  # Return the path to the generated PDF

# Function to export redacted text to Word
def export_to_word(redacted_text):
    # Create a temporary file for Word
    with tempfile.NamedTemporaryFile(delete=False, suffix=".docx") as tmpfile:
        tmpfile.close()  # Close the file to ensure it's saved to disk
        output_word_path = tmpfile.name  # Get the path of the temporary file

    # Create a Word document
    doc = Document()
    doc.add_paragraph(redacted_text)
    
    # Save the redacted Word document to the temporary file path
    doc.save(output_word_path)
    
    return output_word_path  # Return the path to the generated Word document

# Function to handle the entire document processing
def process_pdf(pdf_file):
    try:
        images = pdf_to_images(pdf_file)  # Convert PDF to images
        extracted_text = ocr_from_images(images)  # Extract text from images using EasyOCR
        
        if not extracted_text.strip():
            return None, None, None
            
        redacted_text = redact_sensitive_information(extracted_text)  # Redact sensitive info

        # Export the redacted text to PDF and Word
        output_pdf = export_to_pdf(redacted_text)
        output_word = export_to_word(redacted_text)
        
        return redacted_text, output_pdf, output_word
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
        return None, None, None

# Streamlit app function to handle file upload and download
def main():
    st.title('AI-Powered Document Redaction System')

    # File uploader
    uploaded_pdf = st.file_uploader("Upload a PDF document", type="pdf")
    
    if uploaded_pdf is not None:
        st.write("Processing the PDF...")

        # Process the PDF to extract and redact text
        redacted_text, output_pdf, output_word = process_pdf(uploaded_pdf)

        if redacted_text is None:
            st.error("No redacted text found. Please ensure the document contains extractable text.")
        else:
            # Display redacted text
            st.text_area("Redacted Text", redacted_text, height=300)

            # Allow users to download the redacted PDF
            if output_pdf and os.path.exists(output_pdf):
                with open(output_pdf, "rb") as f:
                    st.download_button("Download Redacted PDF", f.read(), file_name="redacted_output.pdf", mime="application/pdf")

            # Allow users to download the redacted Word document
            if output_word and os.path.exists(output_word):
                with open(output_word, "rb") as f:
                    st.download_button("Download Redacted Word Document", f.read(), file_name="redacted_output.docx", mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")

if __name__ == "__main__":
    main()
