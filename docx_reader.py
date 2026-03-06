from docx import Document
import io

def extract_text_from_docx(file_content: bytes) -> str:
    """
    Extracts text from a Word document (.docx) file content.
    Returns a string containing the text.
    """
    doc = Document(io.BytesIO(file_content))
    text = []
    for para in doc.paragraphs:
        if para.text:
            text.append(para.text)
    return "\n".join(text).strip()
