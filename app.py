from fastapi import FastAPI
from pydantic import BaseModel
import openai
from openai import OpenAI
from openai import AzureOpenAI
from datetime import datetime
import json
from fastapi import FastAPI, Depends,status
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError
from database import get_db
from sqlalchemy import text
from fastapi.responses import JSONResponse


## Please Mention your Azure, Open_API_Key, Model related information.

app = FastAPI()

@app.get("/health")
def unified_health_check(db: Session = Depends(get_db)):
    health_status = {
        "fastapi": "UP",
        "database": "UP",
        "gpt": "UP"
    }

    # Database Check
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        health_status["database"] = "DOWN"

    # GPT Health Check
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini-dev",
            messages=[
                {"role": "system", "content": "Health check"},
                {"role": "user", "content": "ping"}
            ],
            max_tokens=5
        )
        content = response.choices[0].message.content.strip()
        if not content:
            health_status["gpt"] = "DOWN"
    except Exception:
        health_status["gpt"] = "DOWN"

    # Determine overall status
    overall_status = "UP" if all(v == "UP" for v in health_status.values()) else "DOWN"

    return JSONResponse(
        status_code=200 if overall_status == "UP" else 503,
        content={
            "status": overall_status,
            "timestamp": datetime.utcnow().isoformat(),
            "details": health_status
        }
    )


class ChatRequest(BaseModel):
    question: str
    
LOG_FILE = "chat_log.jsonl"

# Endpoint
@app.post("/ask")
async def ask_question(request: ChatRequest):
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,  
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": request.question}
            ]
        )
        answer = response.choices[0].message.content.strip()

        # Prepare log entry
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "question": request.question,
            "answer": answer
        }

        # Append to log file
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")

        return {"response": answer}
    except Exception as e:
        return {"error": str(e)}
    
