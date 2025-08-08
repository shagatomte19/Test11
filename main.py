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

# Enhanced regex patterns for sensitive information
ssn_patterns = [
    r"\b\d{3}-\d{2}-\d{4}\b",  # XXX-XX-XXXX format
    r"\b\d{3}\s\d{2}\s\d{4}\b",  # XXX XX XXXX format
    r"\b\d{9}\b"  # XXXXXXXXX format (9 consecutive digits)
]

credit_card_patterns = [
    r"\b(?:\d{4}[- ]?){3}\d{4}\b",  # XXXX-XXXX-XXXX-XXXX or XXXX XXXX XXXX XXXX
    r"\b\d{13,19}\b"  # 13-19 consecutive digits (covers most card types)
]

# Address patterns - more comprehensive
address_patterns = [
    r"\b\d{1,5}\s+\w+\s+(?:street|st|avenue|ave|road|rd|drive|dr|lane|ln|boulevard|blvd|way|court|ct|place|pl|circle|cir|parkway|pkwy)\.?\b",
    r"\b(?:apt|apartment|suite|ste|unit|#)\s*\d+\b",  # Apartment/Suite numbers
    r"\b\d{5}(?:-\d{4})?\b",  # ZIP codes (XXXXX or XXXXX-XXXX)
    r"\b[A-Z]{2}\s+\d{5}(?:-\d{4})?\b"  # State + ZIP (CA 90210 or CA 90210-1234)
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

# Enhanced function with optional NER for better address detection
def redact_sensitive_information_enhanced(text):
    """
    Alternative function that uses both regex and NER for more accurate address detection.
    Uncomment the ner_model import above to use this function.
    """
    redacted_text = text
    
    # Redact Social Security Numbers
    for pattern in ssn_patterns:
        redacted_text = re.sub(pattern, "[REDACTED SSN]", redacted_text, flags=re.IGNORECASE)
    
    # Redact Credit Card Numbers  
    for pattern in credit_card_patterns:
        redacted_text = re.sub(pattern, "[REDACTED CREDIT CARD]", redacted_text, flags=re.IGNORECASE)
    
    # Redact Addresses using regex
    for pattern in address_patterns:
        redacted_text = re.sub(pattern, "[REDACTED ADDRESS]", redacted_text, flags=re.IGNORECASE)
    
    # Optional: Use NER for additional location detection (only for addresses)
    # Uncomment below if you want to use NER for locations that might be addresses
    """
    try:
        entities = ner_model(text)
        for entity in entities:
            # Only redact locations that look like they could be addresses
            if entity['entity'] in ["B-LOC", "I-LOC"] and len(entity['word']) > 2:
                # Additional check: see if the location is preceded or followed by address indicators
                entity_context = text[max(0, entity['start']-20):entity['end']+20].lower()
                address_indicators = ['street', 'avenue', 'road', 'drive', 'lane', 'blvd', 'apt', 'suite']
                if any(indicator in entity_context for indicator in address_indicators):
                    redacted_text = redacted_text.replace(entity['word'], "[REDACTED ADDRESS]")
    except Exception as e:
        print(f"NER processing error: {e}")
    """
    
    return redacted_text

# Function to process and redact sensitive information using regex only
def redact_sensitive_information(text):
    redacted_text = text
    
    # Redact Social Security Numbers
    for pattern in ssn_patterns:
        redacted_text = re.sub(pattern, "[REDACTED SSN]", redacted_text, flags=re.IGNORECASE)
    
    # Redact Credit Card Numbers
    for pattern in credit_card_patterns:
        redacted_text = re.sub(pattern, "[REDACTED CREDIT CARD]", redacted_text, flags=re.IGNORECASE)
    
    # Redact Addresses
    for pattern in address_patterns:
        redacted_text = re.sub(pattern, "[REDACTED ADDRESS]", redacted_text, flags=re.IGNORECASE)
    
    return redacted_text

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
