# main.py (Clean Human-Readable Review Output in Markdown Format)
import subprocess
import json
import os
import requests
from datetime import datetime
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import storage
from database import SessionLocal, TestResult

# ✅ สร้าง App ครั้งเดียวพร้อมตั้งค่า CORS
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # หรือระบุ URL Streamlit UI บน Cloud Run
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ✅ กำหนดชื่อ GCS Bucket จาก Environment Variable
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "speedtest-artifacts-bucket")
def upload_to_gcs(local_file_path: str, destination_blob_name: str):
    """อัปโหลดไฟล์จาก Local ชั่วคราวขึ้น GCS Bucket"""
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(GCS_BUCKET_NAME)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(local_file_path)
        return f"gs://{GCS_BUCKET_NAME}/{destination_blob_name}"
    except Exception as e:
        print(f"Failed to upload {local_file_path} to GCS: {e}")
        return None

# ✅ อัปเดตชื่อโมเดล Gemini เป็นเวอร์ชันปัจจุบัน
llm = ChatGoogleGenerativeAI(
    model="gemini-3.5-flash",
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY")
)

class PerformanceTestRequest(BaseModel):
    url: str
    executor: str = "shared-iterations"
    vus: int = 2
    duration: str | None = "10s"
    iterations: int | None = 0

K6_GENERATOR_PROMPT = """You are a performance testing expert. Generate a valid JavaScript script for k6.

Target URL: {url}
Executor Type: {executor}
VUs: {vus}
Duration: {duration}
Iterations Target: {iterations}

Requirements:
1. Include imports: `import http from 'k6/http';` and `import {{ check, sleep }} from 'k6';`
2. Define export options matching the chosen Executor ({executor}):
   - If executor is `shared-iterations` or `per-vu-iterations`, set `iterations: {iterations}` in scenarios and do NOT rely strictly on duration.
   - If executor is `constant-vus` or `ramping-vus`, set `duration: '{duration}'`.
3. Include HTTP status check (200 OK) and a brief `sleep(1)` for realism.
4. Output ONLY pure executable JavaScript code. NO markdown backticks (```), NO escaped newlines (\\n).
"""

K6_REVIEWER_PROMPT = """You are a Lead Performance Engineer auditing a k6 test script.
Review the following k6 JavaScript script based on k6 Best Practices:

Script to review:
{script}

Evaluate against these criteria:
1. **Structure & Options**: Are `options` properly exported?
2. **Assertions & Checks**: Are response status checks included?
3. **User Realism**: Is there think time (`sleep`) included?
4. **Syntax & Imports**: Are imports valid for k6?

Provide a clean, beautifully formatted Markdown Code Review Report.
Include:
- ## Overall Status (PASS / FAIL)
- ## Key Strengths
- ## Areas for Improvement / Best Practice Recommendations
Do NOT wrap the output in json or code blocks. Just return formatted Markdown text.
"""

def extract_text_content(content) -> str:
    """แปลง Content จาก LangChain / Gemini ให้เป็น String บริสุทธิ์"""
    if isinstance(content, str):
        return content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(item.get("text", str(item)))
            else:
                parts.append(getattr(item, "text", str(item)))
        return "".join(parts)
    else:
        return str(content)

@app.get("/")
async def health_check():
    """✅ เพิ่ม Health check endpoint ให้ Cloud Run ตรวจสอบสถานะง่ายขึ้น"""
    return {"status": "ok"}

@app.post("/run-test")
async def run_performance_test(req: PerformanceTestRequest):
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="GOOGLE_API_KEY environment variable is not set")

    try:
        # STEP 1: AI Agent 1 - Generate K6 Script
        gen_prompt = ChatPromptTemplate.from_template(K6_GENERATOR_PROMPT)
        gen_chain = gen_prompt | llm
        ai_gen_response = gen_chain.invoke({
            "url": req.url,
            "executor": req.executor,
            "vus": req.vus,
            "duration": req.duration or "100s",
            "iterations": req.iterations or 200
        })
        
        raw_script_text = extract_text_content(ai_gen_response.content)
        k6_script = raw_script_text.replace("```javascript", "").replace("```js", "").replace("```", "").strip()
        if "\\n" in k6_script:
            k6_script = k6_script.replace("\\n", "\n")

        # STEP 2: AI Agent 2 - Review Code against Best Practices
        review_prompt = ChatPromptTemplate.from_template(K6_REVIEWER_PROMPT)
        review_chain = review_prompt | llm
        ai_review_response = review_chain.invoke({"script": k6_script})
        
        raw_review_text = extract_text_content(ai_review_response.content)
        review_md_content = raw_review_text.replace("```markdown", "").replace("```", "").strip()
        if "\\n" in review_md_content:
            review_md_content = review_md_content.replace("\\n", "\n")

        # STEP 3: Setup Folders & Save Files
        os.makedirs("scripts", exist_ok=True)
        os.makedirs("summaries", exist_ok=True)
        os.makedirs("reviews", exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        script_path = f"scripts/test_script_{timestamp}.js"
        summary_path = f"summaries/summary_{timestamp}.json"
        review_path = f"reviews/review_{timestamp}.md"

        with open(script_path, "w", encoding="utf-8") as f:
            f.write(k6_script)

        report_header = f"""# 🔍 K6 Code Review Report
- **Timestamp:** {timestamp}
- **Target URL:** {req.url}
- **Script File:** `{script_path}`

---

"""
        with open(review_path, "w", encoding="utf-8") as f:
            f.write(report_header + review_md_content)

        # STEP 4: Run K6 Execution
        cmd = [
            "k6", "run",
            "--summary-export", summary_path,
            script_path
        ]

        process = subprocess.run(cmd, capture_output=True, text=True)
        
        if process.returncode != 0:
            raise HTTPException(status_code=500, detail=f"k6 execution error: {process.stderr}")

        if not os.path.exists(summary_path):
            raise HTTPException(status_code=500, detail=f"k6 finished but no summary created. Output: {process.stdout}")

        # STEP 5: Upload Files to GCS & Return UI Payload
        with open(summary_path, "r", encoding="utf-8") as f:
            metrics_data = json.load(f)
        metrics = metrics_data.get("metrics", {})
        http_reqs_data = metrics.get("http_reqs", {})
        http_reqs_vals = http_reqs_data.get("values", http_reqs_data) if isinstance(http_reqs_data, dict) else {}

        duration_data = metrics.get("http_req_duration", {})
        duration_vals = duration_data.get("values", duration_data) if isinstance(duration_data, dict) else {}

        # หลังจากคำนวณ summary_result เสร็จแล้ว ก่อนบรรทัด return summary_result ให้เพิ่ม:
        db = SessionLocal()
        db_result = TestResult(
                target_url=req.url,
                executor=req.executor,
                vus=req.vus,
                total_requests=int(http_reqs_vals.get("count", 0)),
                rps=round(float(http_reqs_vals.get("rate", 0)), 2),
                avg_response_time_ms=round(float(duration_vals.get("avg", 0)), 2),
                p95_response_time_ms=round(float(duration_vals.get("p(95)", duration_vals.get("pt(95)", 0))), 2)
            )
        db.add(db_result)
        db.commit()
        db.refresh(db_result)
        db.close()

        # STEP 6: Upload Files silently to GCS (อัปโหลดลง GCS เบื้องหลัง)
        upload_to_gcs(script_path, f"scripts/test_script_{timestamp}.js")
        upload_to_gcs(review_path, f"reviews/review_{timestamp}.md")
        upload_to_gcs(summary_path, f"summaries/summary_{timestamp}.json")

        summary_result = {
            "status": "Success",
            "target_url": req.url,
            "executor": req.executor,
            "total_requests": int(http_reqs_vals.get("count", 0)),
            "rps": round(float(http_reqs_vals.get("rate", 0)), 2),
            "avg_response_time_ms": round(float(duration_vals.get("avg", 0)), 2),
            "p95_response_time_ms": round(float(duration_vals.get("p(95)", duration_vals.get("pt(95)", 0))), 2),
        }
        return summary_result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))