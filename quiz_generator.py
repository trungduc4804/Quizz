import os
import json
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

# We look for GEMINI_API_KEY in the environment
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    # Just in case they provide it some other way but it should be set
    print("Warning: GEMINI_API_KEY environment variable not set.")

client = genai.Client(api_key=api_key)

def generate_quiz_from_text(text: str, num_questions: int = 10) -> list[dict]:
    """
    Calls Google GenAI to generate a multiple choice quiz from the given text.
    Returns a list of dictionaries with questions and options.
    """
    if len(text) > 100000: # Limit text size to avoid huge token usage if needed
        text = text[:100000]

    prompt = f"""
    You are an expert educator. I will provide you with a text document.
    First, detect the EXACT primary language and writing system of the text document.
    Then, generate a multiple-choice quiz based on this text.
    
    IMPORTANT CRITICAL RULES FOR LANGUAGE:
    - The ENTIRE output (the generated questions, options A/B/C/D, and explanations) MUST ABSOLUTELY be written in the EXACT SAME LANGUAGE and characters as the provided text.
    - For example: if the text is in Chinese, the questions, options, and explanations MUST be in Chinese.
    - DO NOT auto-translate anything to English or Vietnamese unless the original text itself is in English or Vietnamese.

    Create exactly {num_questions} questions.
    Each question must have exactly 4 options (A, B, C, D) and exactly 1 correct answer.
    Provide a brief explanation for why the answer is correct (in the same language as the text).

    The response MUST be ONLY a valid JSON array of objects. Do not include any markdown formatting like ```json.
    Each object must strictly have this schema:
    {{
        "text": "The question text",
        "option_a": "Option A text",
        "option_b": "Option B text",
        "option_c": "Option C text",
        "option_d": "Option D text",
        "correct_option": "A" (or "B", "C", "D"),
        "explanation": "Brief explanation of the answer"
    }}

    Text document:
    {text}
    """

    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0.2,
            response_mime_type="application/json",
        ),
    )
    
    try:
        data = json.loads(response.text)
        return data
    except Exception as e:
        print(f"Error parsing JSON from GenAI: {e}")
        print(f"Raw response: {response.text}")
        # Attempt to clean potential markdown anyway just in case
        clean_text = response.text.strip()
        if clean_text.startswith("```json"):
            clean_text = clean_text[7:]
        if clean_text.endswith("```"):
            clean_text = clean_text[:-3]
        try:
            return json.loads(clean_text)
        except:
            raise ValueError("Failed to parse the generated quiz from AI.")
