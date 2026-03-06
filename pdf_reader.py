from pypdf import PdfReader
import io

def extract_text_from_pdf(file_content: bytes) -> str:
    """
    Extracts text from a PDF file content.
    Returns a string containing the text.
    """
    reader = PdfReader(io.BytesIO(file_content))
    text = ""
    for page in reader.pages:
        page_text = page.extract_text()
        if page_text:
            text += page_text + "\n"
    return text.strip()
