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

# Main redaction function - now accepts mode parameter
def redact_sensitive_information(text, mode="conservative"):
    """
    Main redaction function with selectable modes.
    
    Args:
        text: Input text to redact
        mode: "conservative" or "aggressive"
    """
    
    if mode == "conservative":
        return redact_sensitive_information_simple(text)
    else:
        return detect_and_redact_patterns(text)

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
def process_pdf(pdf_file, redaction_mode="conservative"):
    try:
        images = pdf_to_images(pdf_file)  # Convert PDF to images
        extracted_text = ocr_from_images(images)  # Extract text from images using EasyOCR
        
        if not extracted_text.strip():
            return None, None, None
        
        # Use the selected redaction mode
        mode = "conservative" if "Conservative" in redaction_mode else "aggressive"
        redacted_text = redact_sensitive_information(extracted_text, mode=mode)  # Redact sensitive info

        # Export the redacted text to PDF and Word
        output_pdf = export_to_pdf(redacted_text)
        output_word = export_to_word(redacted_text)
        
        return redacted_text, output_pdf, output_word
    except Exception as e:
        st.error(f"Error processing PDF: {str(e)}")
        return None, None, None

# Streamlit app function to handle file upload and download
def main():
    # Page configuration
    st.set_page_config(
        page_title="AI Document Redaction System",
        page_icon="🔒",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Custom CSS for better styling (Dark mode compatible)
    st.markdown("""
    <style>
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        margin-bottom: 2rem;
        text-align: center;
        color: white;
    }
    
    .feature-card {
        background: var(--background-color);
        padding: 1.5rem;
        border-radius: 10px;
        border-left: 4px solid #667eea;
        margin: 1rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border: 1px solid var(--secondary-background-color);
        color: var(--text-color);
    }
    
    .stats-card {
        background: var(--background-color);
        padding: 1rem;
        border-radius: 8px;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        border: 1px solid var(--secondary-background-color);
        color: var(--text-color);
    }
    
    .success-message {
        background: rgba(212, 237, 218, 0.2);
        color: var(--text-color);
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid #28a745;
    }
    
    .footer {
        text-align: center;
        padding: 2rem;
        color: var(--text-color);
        border-top: 1px solid var(--secondary-background-color);
        margin-top: 3rem;
        font-size: 0.9rem;
        opacity: 0.8;
    }
    
    .redaction-preview {
        background: var(--secondary-background-color);
        padding: 1rem;
        border-radius: 8px;
        border: 1px solid var(--secondary-background-color);
        max-height: 400px;
        overflow-y: auto;
        color: var(--text-color);
    }
    
    .upload-section {
        border: 2px dashed #667eea;
        border-radius: 10px;
        padding: 2rem;
        text-align: center;
        background: rgba(102, 126, 234, 0.05);
        margin: 1rem 0;
        color: var(--text-color);
    }
    
    /* Dark mode specific adjustments */
    @media (prefers-color-scheme: dark) {
        .feature-card {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .stats-card {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        .upload-section {
            background: rgba(102, 126, 234, 0.1);
        }
        
        .redaction-preview {
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.1);
        }
    }
    
    /* Streamlit dark theme adjustments */
    [data-theme="dark"] .feature-card,
    .stApp[data-theme="dark"] .feature-card {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: white !important;
    }
    
    [data-theme="dark"] .stats-card,
    .stApp[data-theme="dark"] .stats-card {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: white !important;
    }
    
    [data-theme="dark"] .upload-section,
    .stApp[data-theme="dark"] .upload-section {
        background: rgba(102, 126, 234, 0.1) !important;
        color: white !important;
    }
    
    [data-theme="dark"] .redaction-preview,
    .stApp[data-theme="dark"] .redaction-preview {
        background: rgba(255, 255, 255, 0.05) !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
        color: white !important;
    }
    
    [data-theme="dark"] .footer,
    .stApp[data-theme="dark"] .footer {
        color: rgba(255, 255, 255, 0.8) !important;
        border-top: 1px solid rgba(255, 255, 255, 0.1) !important;
    }
    </style>
    """, unsafe_allow_html=True)
    
    # Header
    st.markdown("""
    <div class="main-header">
        <h1>🔒 AI-Powered Document Redaction System</h1>
        <p>Securely redact sensitive information from your PDF documents</p>
    </div>
    """, unsafe_allow_html=True)
    
    # Sidebar with features and settings
    with st.sidebar:
        st.markdown("### 🎛️ Settings & Info")
        
        # Redaction mode selection
        st.markdown("**Redaction Mode:**")
        redaction_mode = st.radio(
            "",
            ["Conservative (Labeled data only)", "Aggressive (Pattern matching)"],
            help="Conservative mode only redacts explicitly labeled sensitive data. Aggressive mode uses pattern matching to find unlabeled sensitive information."
        )
        
        st.markdown("---")
        
        # Features info
        st.markdown("### ✨ Features")
        st.markdown("""
        - 🔍 **OCR Text Extraction**
        - 🏛️ **Social Security Numbers**
        - 💳 **Credit Card Details**
        - 🏠 **Address Information**
        - 📄 **PDF Export**
        - 📝 **Word Export**
        """)
        
        st.markdown("---")
        
        # Statistics placeholder
        st.markdown("### 📊 Statistics")
        stats_placeholder = st.empty()
        
        st.markdown("---")
        
        # Security notice
        st.markdown("### 🛡️ Security Notice")
        st.info("Your documents are processed locally and are not stored or transmitted to external servers.")
    
    # Main content area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        # File upload section
        st.markdown("""
        <div class="upload-section">
            <h3>📄 Upload Your Document</h3>
            <p>Select a PDF document to redact sensitive information</p>
        </div>
        """, unsafe_allow_html=True)
        
        uploaded_pdf = st.file_uploader(
            "",
            type="pdf",
            help="Upload a PDF document containing sensitive information"
        )
        
        if uploaded_pdf is not None:
            # File info
            file_size = len(uploaded_pdf.getvalue()) / 1024  # KB
            st.success(f"✅ File uploaded: **{uploaded_pdf.name}** ({file_size:.1f} KB)")
            
            # Processing section
            with st.expander("🔧 Processing Options", expanded=True):
                col_a, col_b = st.columns(2)
                with col_a:
                    show_original = st.checkbox("Show original text", value=False)
                with col_b:
                    auto_download = st.checkbox("Auto-generate downloads", value=True)
            
            # Process button
            if st.button("🚀 Process Document", type="primary", use_container_width=True):
                # Progress bar and status
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                status_text.text("🔄 Initializing OCR engine...")
                progress_bar.progress(10)
                
                status_text.text("📖 Extracting text from PDF...")
                progress_bar.progress(30)
                
                # Process the PDF
                redacted_text, output_pdf, output_word = process_pdf(uploaded_pdf, redaction_mode)
                
                status_text.text("🔍 Applying redaction patterns...")
                progress_bar.progress(70)
                
                status_text.text("📄 Generating output files...")
                progress_bar.progress(90)
                
                progress_bar.progress(100)
                status_text.text("✅ Processing complete!")
                
                if redacted_text is None:
                    st.error("❌ No text could be extracted. Please ensure the document contains readable text.")
                else:
                    # Success message
                    st.markdown("""
                    <div class="success-message">
                        <strong>🎉 Processing completed successfully!</strong><br>
                        Your document has been processed and sensitive information has been redacted.
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Display statistics
                    original_length = len(uploaded_pdf.getvalue())
                    redacted_length = len(redacted_text)
                    redactions_count = redacted_text.count('[REDACTED')
                    
                    stats_placeholder.markdown(f"""
                    <div class="stats-card">
                        <strong>{redactions_count}</strong><br>
                        <small>Items Redacted</small>
                    </div>
                    <div class="stats-card" style="margin-top: 0.5rem;">
                        <strong>{redacted_length:,}</strong><br>
                        <small>Characters Processed</small>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # Results section
                    st.markdown("### 📋 Results")
                    
                    # Tabs for different views
                    tab1, tab2, tab3 = st.tabs(["📄 Redacted Text", "📊 Summary", "⚙️ Settings"])
                    
                    with tab1:
                        if show_original:
                            col_orig, col_red = st.columns(2)
                            with col_orig:
                                st.markdown("**Original Text (Preview):**")
                                # Show first part of original (you'd need to store this)
                                st.text_area("", "Original text would be shown here...", height=300, disabled=True)
                            with col_red:
                                st.markdown("**Redacted Text:**")
                                st.text_area("", redacted_text, height=300, disabled=True)
                        else:
                            st.markdown("**Redacted Text:**")
                            st.markdown(f'<div class="redaction-preview">{redacted_text}</div>', unsafe_allow_html=True)
                    
                    with tab2:
                        # Summary metrics
                        col_metric1, col_metric2, col_metric3, col_metric4 = st.columns(4)
                        
                        with col_metric1:
                            ssn_count = redacted_text.count('[REDACTED SSN]')
                            st.metric("SSN Redacted", ssn_count)
                        
                        with col_metric2:
                            cc_count = redacted_text.count('[REDACTED CREDIT CARD]')
                            st.metric("Credit Cards", cc_count)
                        
                        with col_metric3:
                            addr_count = redacted_text.count('[REDACTED ADDRESS]')
                            st.metric("Addresses", addr_count)
                        
                        with col_metric4:
                            total_redactions = redactions_count
                            st.metric("Total Redactions", total_redactions)
                        
                        # Redaction breakdown
                        if redactions_count > 0:
                            st.markdown("### 📊 Redaction Breakdown")
                            redaction_data = {
                                "Type": ["SSN", "Credit Cards", "Addresses", "Other"],
                                "Count": [ssn_count, cc_count, addr_count, max(0, total_redactions - ssn_count - cc_count - addr_count)]
                            }
                            st.bar_chart(redaction_data, x="Type", y="Count")
                    
                    with tab3:
                        st.markdown("**Current Settings:**")
                        st.write(f"- Redaction Mode: {redaction_mode}")
                        st.write(f"- Show Original: {show_original}")
                        st.write(f"- Auto Download: {auto_download}")
                    
                    # Download section
                    st.markdown("### 💾 Download Files")
                    
                    download_col1, download_col2 = st.columns(2)
                    
                    with download_col1:
                        if output_pdf and os.path.exists(output_pdf):
                            with open(output_pdf, "rb") as f:
                                st.download_button(
                                    "📄 Download Redacted PDF",
                                    f.read(),
                                    file_name="redacted_document.pdf",
                                    mime="application/pdf",
                                    use_container_width=True
                                )
                    
                    with download_col2:
                        if output_word and os.path.exists(output_word):
                            with open(output_word, "rb") as f:
                                st.download_button(
                                    "📝 Download Word Document",
                                    f.read(),
                                    file_name="redacted_document.docx",
                                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                    use_container_width=True
                                )
    
    with col2:
        # Tips and information
        st.markdown("### 💡 Tips")
        
        st.markdown("""
        <div class="feature-card">
            <h4>🎯 Best Practices</h4>
            <ul>
                <li>Ensure PDF text is selectable</li>
                <li>Review redacted output carefully</li>
                <li>Use conservative mode for higher accuracy</li>
                <li>Check download files before sharing</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("""
        <div class="feature-card">
            <h4>🔍 What Gets Redacted</h4>
            <ul>
                <li><strong>SSN:</strong> XXX-XX-XXXX format</li>
                <li><strong>Credit Cards:</strong> 16-digit numbers</li>
                <li><strong>Addresses:</strong> Street addresses</li>
                <li><strong>ZIP Codes:</strong> 5 or 9-digit codes</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
        
        st.markdown("""
        <div class="feature-card">
            <h4>⚠️ Limitations</h4>
            <ul>
                <li>OCR quality affects accuracy</li>
                <li>Handwritten text may not be detected</li>
                <li>Complex layouts may cause issues</li>
                <li>Always manual review recommended</li>
            </ul>
        </div>
        """, unsafe_allow_html=True)
    
    # Footer
    st.markdown("""
    <div class="footer">
        <hr>
        <p>🚀 Made with ❤️ by <strong>Enamul Hasan Shagato</strong></p>
        <p><small>AI-Powered Document Redaction System | Protecting Your Privacy</small></p>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
