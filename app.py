import os
import json
from fastapi import FastAPI, Depends, Request, UploadFile, File, Form, HTTPException, status, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List

from database import engine, Base, get_db, Quiz, Question, QuizAttempt, User
from pdf_reader import extract_text_from_pdf
from docx_reader import extract_text_from_docx
from quiz_generator import generate_quiz_from_text
from auth import verify_password, get_password_hash, create_access_token, get_current_user, get_current_active_user, ACCESS_TOKEN_EXPIRE_MINUTES
from datetime import timedelta

# Initialize App
app = FastAPI(title="PDF to Quiz AI")

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Models for API requests
class QuestionEditModel(BaseModel):
    id: int | None = None
    text: str
    option_a: str
    option_b: str
    option_c: str
    option_d: str
    correct_option: str
    explanation: str | None = None

class QuizUpdateModel(BaseModel):
    time_limit: int
    shuffle_questions: bool
    shuffle_options: bool
    questions: List[QuestionEditModel]

class SubmitAnswerModel(BaseModel):
    answers: dict[str, str] # e.g. {"1": "A", "2": "C"} mapping question ID to chosen option
    time_taken: int

# UI Routes
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, current_user: User = Depends(get_current_user)):
    return templates.TemplateResponse("upload.html", {"request": request, "current_user": current_user})

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    # Lấy các bài kiểm tra được sắp xếp mới nhất lên đầu
    quizzes = db.query(Quiz).filter(Quiz.user_id == current_user.id).order_by(Quiz.id.desc()).all()
    # Lấy thêm số lượt đã tạo/khảo sát cho các đề thi
    quiz_data = []
    for q in quizzes:
        attempts_count = db.query(QuizAttempt).filter(QuizAttempt.quiz_id == q.id).count()
        quiz_data.append({
            "quiz": q,
            "attempts_count": attempts_count
        })
    return templates.TemplateResponse("dashboard.html", {"request": request, "quiz_data": quiz_data, "current_user": current_user})

@app.get("/preview/{quiz_id}", response_class=HTMLResponse)
async def preview_quiz(request: Request, quiz_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return templates.TemplateResponse("edit.html", {"request": request, "quiz": quiz, "current_user": current_user})

@app.get("/take/{quiz_id}", response_class=HTMLResponse)
async def take_quiz(request: Request, quiz_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    return templates.TemplateResponse("quiz.html", {"request": request, "quiz": quiz, "current_user": current_user})

@app.get("/result/{attempt_id}", response_class=HTMLResponse)
async def result(request: Request, attempt_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    attempt = db.query(QuizAttempt).filter(QuizAttempt.id == attempt_id).first()
    if not attempt:
        raise HTTPException(status_code=404, detail="Attempt not found")
    
    quiz = db.query(Quiz).filter(Quiz.id == attempt.quiz_id).first()
    
    user_answers = {}
    if attempt.answers_json:
        user_answers = json.loads(attempt.answers_json)

    return templates.TemplateResponse("result.html", {
        "request": request, 
        "attempt": attempt, 
        "quiz": quiz,
        "user_answers": user_answers,
        "current_user": current_user
    })

# API Routes
@app.post("/register")
async def register(
    username: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user_db = db.query(User).filter(User.username == username).first()
    if user_db:
        return RedirectResponse(url="/login?error=username", status_code=303)
    
    email_db = db.query(User).filter(User.email == email).first()
    if email_db:
        # Redirect back to login with an error flag specifically for email if you prefer, or just raise 400
        # Wait, the frontend handles error=credentials for login, but for register it just submits POST.
        # So we can return a redirect with error=email
        return RedirectResponse(url="/login?error=email", status_code=303)
    
    hashed_password = get_password_hash(password)
    new_user = User(username=username, email=email, hashed_password=hashed_password)
    db.add(new_user)
    db.commit()
    return RedirectResponse(url="/login?registered=1", status_code=303)

@app.post("/login")
async def login(
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.hashed_password):
        # Redirect back to login with an error flag
        return RedirectResponse(url="/login?error=credentials", status_code=303)
        
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.username}, expires_delta=access_token_expires
    )
    
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(
        key="access_token", 
        value=f"Bearer {access_token}", 
        httponly=True, 
        samesite="lax"
    )
    return response

@app.get("/logout")
async def logout(response: Response):
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("access_token")
    return response

@app.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    title: str = Form("Untitled Quiz"),
    question_count: int = Form(10),
    time_limit: int = Form(10),
    shuffle_questions: bool = Form(False),
    shuffle_options: bool = Form(False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    try:
        # Read file content
        content = await file.read()
        
        # Extract Text based on file type
        filename_lower = file.filename.lower()
        if filename_lower.endswith('.pdf'):
            text = extract_text_from_pdf(content)
        elif filename_lower.endswith('.docx'):
            text = extract_text_from_docx(content)
        else:
            raise HTTPException(status_code=400, detail="Unsupported file format. Please upload PDF or DOCX.")

        if not text:
            raise HTTPException(status_code=400, detail="Could not extract text from document")

        # Call AI
        questions_data = generate_quiz_from_text(text, num_questions=question_count)

        # Create Quiz Record
        new_quiz = Quiz(
            user_id=current_user.id,
            title=title if title.strip() else "Untitled Quiz",
            filename=file.filename,
            question_count=len(questions_data),
            time_limit=time_limit,
            shuffle_questions=shuffle_questions,
            shuffle_options=shuffle_options
        )
        db.add(new_quiz)
        db.commit()
        db.refresh(new_quiz)

        # Create Questions Records
        for q_data in questions_data:
            new_q = Question(
                quiz_id=new_quiz.id,
                text=q_data['text'],
                option_a=q_data['option_a'],
                option_b=q_data['option_b'],
                option_c=q_data['option_c'],
                option_d=q_data['option_d'],
                correct_option=q_data['correct_option'],
                explanation=q_data.get('explanation', '')
            )
            db.add(new_q)
        db.commit()

        # Redirect to preview
        return RedirectResponse(url=f"/preview/{new_quiz.id}", status_code=303)

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/quiz/{quiz_id}/update")
async def update_quiz(quiz_id: int, data: QuizUpdateModel, db: Session = Depends(get_db), current_user: User = Depends(get_current_active_user)):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id, Quiz.user_id == current_user.id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    quiz.time_limit = data.time_limit
    quiz.shuffle_questions = data.shuffle_questions
    quiz.shuffle_options = data.shuffle_options
    
    # Update questions
    # First, delete existing
    db.query(Question).filter(Question.quiz_id == quiz_id).delete()
    
    # Then add new ones from data
    for q_data in data.questions:
        new_q = Question(
            quiz_id=quiz_id,
            text=q_data.text,
            option_a=q_data.option_a,
            option_b=q_data.option_b,
            option_c=q_data.option_c,
            option_d=q_data.option_d,
            correct_option=q_data.correct_option,
            explanation=q_data.explanation
        )
        db.add(new_q)
    
    # Update correct count
    quiz.question_count = len(data.questions)

    db.commit()
    return {"message": "Quiz updated successfully"}

@app.get("/api/quiz/{quiz_id}")
async def get_quiz_api(quiz_id: int, db: Session = Depends(get_db)):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")
    
    questions = db.query(Question).filter(Question.quiz_id == quiz_id).all()
    q_out = []
    for q in questions:
        q_out.append({
            "id": q.id,
            "text": q.text,
            "option_a": q.option_a,
            "option_b": q.option_b,
            "option_c": q.option_c,
            "option_d": q.option_d,
            "correct_option": q.correct_option, # Usually bad practice to send correct option to frontend, but we keep it simple for now, or check on backend
            "explanation": q.explanation
        })
    
    return {
        "id": quiz.id,
        "time_limit": quiz.time_limit,
        "shuffle_questions": quiz.shuffle_questions,
        "shuffle_options": quiz.shuffle_options,
        "questions": q_out
    }

@app.post("/api/quiz/{quiz_id}/submit")
async def submit_quiz(quiz_id: int, data: SubmitAnswerModel, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    quiz = db.query(Quiz).filter(Quiz.id == quiz_id).first()
    if not quiz:
        raise HTTPException(status_code=404, detail="Quiz not found")

    questions = db.query(Question).filter(Question.quiz_id == quiz_id).all()
    q_dict = {str(q.id): q for q in questions}

    score = 0
    total = len(questions)

    for q_id_str, user_ans in data.answers.items():
        if q_id_str in q_dict:
            if q_dict[q_id_str].correct_option == user_ans:
                score += 1
    
    attempt = QuizAttempt(
        user_id=current_user.id if current_user else None,
        quiz_id=quiz.id,
        score=score,
        total_questions=total,
        time_taken=data.time_taken,
        answers_json=json.dumps(data.answers)
    )
    db.add(attempt)
    db.commit()
    db.refresh(attempt)

    return {"attempt_id": attempt.id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)

from starlette.exceptions import HTTPException as StarletteHTTPException

@app.exception_handler(StarletteHTTPException)
async def custom_http_exception_handler(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        response = RedirectResponse(url="/login", status_code=303)
        response.delete_cookie("access_token")
        return response
    if exc.status_code == 429:
         return HTMLResponse(content="""
         <div style='text-align: center; font-family: sans-serif; padding: 50px;'>
            <h1 style='color: red;'>Lỗi Hệ Thống AI (Mã 429)</h1>
            <p>Hệ thống AI (Gemini) đã hết hạn mức sử dụng (Quota Exhausted) trong ngày/phút.</p>
            <p>Vui lòng đợi vài phút rồi thử lại sau, hoặc kiểm tra lại Key API.</p>
            <a href='/' style='Root'>Quay Yê Trang Chủ</a>
         </div>
         """, status_code=429)

    return HTMLResponse(content=f"Error {exc.status_code}: {exc.detail}", status_code=exc.status_code)

@app.exception_handler(Exception)
async def validation_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    
    # Catching Google GenAI Exhausted string explicitly if it escapes the HTTP handler
    error_str = str(exc)
    if "RESOURCE_EXHAUSTED" in error_str or "quota" in error_str.lower():
         return HTMLResponse(content="""
         <div style='text-align: center; font-family: sans-serif; padding: 50px;'>
            <h1 style='color: #ef4444;'>Lỗi Hệ Thống AI Đầy Tải</h1>
            <p style='color: white;'>Hệ thống Google AI hiện đang bị quá tải hoặc đã hết giới hạn sử dụng miễn phí cho tài khoản của bạn.</p>
            <p style='color: #94a3b8;'>Vui lòng thử lại sau vài phút!</p>
            <br>
            <a href='/' style='padding: 10px 20px; background: #3b82f6; color: white; text-decoration: none; border-radius: 5px;'>Quay Lại Trang Chủ</a>
         </div>
         """, status_code=500)

    # Hiển thị thông báo lỗi chi tiết thay vì "Internal Error" để dễ debug trên Render
    return HTMLResponse(
        content=f"<div style='color: white; padding: 20px; font-family: sans-serif;'><h1>Internal Error</h1><p>Chi tiết lỗi:</p><pre>{error_str}</pre><br><a href='/' style='color: #3b82f6;'>Quay Lại Trang Chủ</a></div>", 
        status_code=500
    )
