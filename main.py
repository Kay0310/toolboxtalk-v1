from fastapi import FastAPI, File, UploadFile, Form, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from pydantic import BaseModel
import os
import uuid
import shutil
import openai
from dotenv import load_dotenv
from jose import jwt, JWTError
from datetime import datetime, timedelta
import json

load_dotenv()

app = FastAPI()

openai.api_key = os.getenv("OPENAI_API_KEY", "sk-...")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = "uploads"
MINUTES_STORE = "minutes.json"
os.makedirs(UPLOAD_DIR, exist_ok=True)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "1234"
SECRET_KEY = "supersecretkey"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login")

def create_access_token(data: dict, expires_delta: timedelta = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return username
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

@app.post("/api/login")
async def login(form_data: OAuth2PasswordRequestForm = Depends()):
    if form_data.username != ADMIN_USERNAME or form_data.password != ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = create_access_token(data={"sub": form_data.username},
                                       expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    return {"access_token": access_token, "token_type": "bearer"}

@app.post("/api/upload")
async def upload_audio(file: UploadFile = File(...)):
    ext = file.filename.split(".")[-1]
    uid = str(uuid.uuid4())
    file_path = f"{UPLOAD_DIR}/{uid}.{ext}"

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    transcript = ""
    try:
        with open(file_path, "rb") as audio_file:
            response = openai.Audio.transcribe("whisper-1", audio_file, language="ko")
            transcript = response.get("text", "")
    except Exception as e:
        return {"error": str(e)}

    return {"message": "파일 업로드 및 변환 완료", "text": transcript, "filename": file_path}

@app.post("/api/minutes")
async def save_minutes(
    date: str = Form(...),
    location: str = Form(...),
    attendees: str = Form(...),
    content: str = Form(...),
):
    record = {
        "date": date,
        "location": location,
        "attendees": attendees.split(","),
        "content": content,
    }
    try:
        if os.path.exists(MINUTES_STORE):
            with open(MINUTES_STORE, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = []
        data.append(record)
        with open(MINUTES_STORE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        return {"error": str(e)}

    return {"message": "회의록이 저장되었습니다.", "data": record}

@app.get("/api/minutes")
async def get_minutes(user: str = Depends(get_current_user)):
    if os.path.exists(MINUTES_STORE):
        with open(MINUTES_STORE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"minutes": data}
    return {"minutes": []}

@app.post("/api/minutes/update")
async def update_minutes(request: Request, user: str = Depends(get_current_user)):
    payload = await request.json()
    idx = payload.get("index")
    if idx is None:
        raise HTTPException(status_code=400, detail="인덱스가 필요합니다")

    if not os.path.exists(MINUTES_STORE):
        raise HTTPException(status_code=404, detail="저장된 회의록 없음")

    with open(MINUTES_STORE, "r", encoding="utf-8") as f:
        data = json.load(f)

    if idx < 0 or idx >= len(data):
        raise HTTPException(status_code=400, detail="유효하지 않은 인덱스")

    data[idx] = {
        "date": payload.get("date"),
        "location": payload.get("location"),
        "attendees": payload.get("attendees"),
        "content": payload.get("content"),
    }

    with open(MINUTES_STORE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return {"message": "수정 완료", "data": data[idx]}