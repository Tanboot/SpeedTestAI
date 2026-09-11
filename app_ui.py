# app.py (Streamlit UI)
import streamlit as st
import requests

st.set_page_config(
    page_title="AI Performance Test",  # <--- เปลี่ยนชื่อ Title ที่ต้องการตรงนี้
    page_icon="⚡",                      # <--- เปลี่ยนไอคอนบนแท็บ (ใส่ Emoji หรือ path รูปภาพได้)
)
st.title("⚡ AI-Powered Performance Test")

url = st.text_input("Target URL", "https://jsonplaceholder.typicode.com/posts/1")

# เปลี่ยนเป็นตัวเลือก Executor
executor = st.selectbox(
    "Choose k6 Executor",
    [
        "shared-iterations (เน้นจำนวน Request ครบตามเป้า)",
        "per-vu-iterations (เน้นให้ VU ทุกตัวยิงครบจำนวนรอบเท่ากัน)",
        "constant-vus (เน้นยิงต่อเนื่องตามเวลา Duration)",
        "ramping-vus (เน้นทยอยเพิ่ม/ลด VU ตามเวลา)"
    ]
)

# สกัดเอาชื่อ Executor หลักไปใช้งาน (เช่น shared-iterations)
executor_type = executor.split(" ")[0]

vus = st.number_input("Virtual Users (VUs)", min_value=1, value=2)

# แสดงช่อง Input ให้เหมาะสมตาม Executor ที่เลือก
if executor_type in ["shared-iterations", "per-vu-iterations"]:
    iterations = st.number_input("Total Requests / Iterations Target", min_value=1, value=200)
    duration = None
else:
    duration = st.text_input("Duration", "100s")
    iterations = None

if st.button("ทดสอบ"):
    payload = {
        "url": url,
        "executor": executor_type,
        "vus": vus,
        "duration": duration,
        "iterations": iterations
    }
    
    with st.spinner("AI กำลังสร้าง Script, Review และสั่งรัน K6..."):
        try:
            response = requests.post("http://fastapi-backend:8000/run-test", json=payload, timeout=120)
            if response.status_code == 200:
                st.success("ทดสอบเรียบร้อย!")
                st.json(response.json())
            else:
                st.error(f"เกิดข้อผิดพลาด: {response.text}")
        except Exception as e:
            st.error(f"ไม่สามารถเชื่อมต่อ Backend ได้: {e}")