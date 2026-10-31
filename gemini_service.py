import os
import json
import time
import urllib.request
import urllib.error

def _load_env_file(path=".env"):
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except FileNotFoundError:
        pass
    except Exception:
        pass

_load_env_file()

GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')
# โมเดล Free Tier ของ Google AI Studio (เรียงจากใหม่/เร็ว → เก่า/สำรอง)
GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]
GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'

_gemini_available = None
_active_model = None
_preferred_model = os.environ.get('GEMINI_MODEL') or None

def load_gemini_models():
    global _gemini_available
    if _gemini_available is not None:
        return _gemini_available
    try:
        req = urllib.request.Request(
            f'{GEMINI_BASE_URL}/models?key={GEMINI_API_KEY}',
            headers={'Content-Type': 'application/json'},
            method='GET'
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        models = data.get('models', [])
        _gemini_available = set(m.get('name', '').replace('models/', '') for m in models)
    except Exception:
        _gemini_available = None
    return _gemini_available

def gemini_candidate_models():
    available = load_gemini_models()
    ordered = []
    if _preferred_model:
        ordered.append(_preferred_model)
    ordered += [m for m in GEMINI_MODELS if m != _preferred_model]
    if available is not None:
        ordered = [m for m in ordered if m in available]
    return ordered

def build_gemini_payload(question, chat_history):
    recent = chat_history[-20:]
    context_lines = []
    for entry in recent:
        context_lines.append(f"{entry['sender']} -> {entry['target']}: {entry['message']}")
    context_text = "\n".join(context_lines) if context_lines else "(ยังไม่มีประวัติแชท)"

    prompt = (
        "คุณคือผู้ช่วยชื่อ GeminiBot ทำงานในระบบแชท socket ตอบเป็นภาษาไทยเท่านั้น "
        "สุภาพ กระชับ ตรงประเด็น\n\n"
        f"ประวัติแชทล่าสุด (บริบท):\n{context_text}\n\n"
        f"คำถามปัจจุบัน: {question}\n\n"
        "โปรดตอบคำถามปัจจุบันเป็นภาษาไทย หากข้อมูลในประวัติช่วยตอบได้ ให้นำมาใช้อ้างอิงได้"
    )
    return {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048},
    }

def extract_gemini_text(result):
    candidates = result.get('candidates', [])
    if candidates:
        parts = candidates[0].get('content', {}).get('parts', [])
        if parts:
            return parts[0].get('text', 'ขออภัย ไม่สามารถตอบคำถามนี้ได้ในขณะนี้')
    return None

def call_gemini_api(question, chat_history):
    global _active_model
    if not GEMINI_API_KEY:
        return "ขออภัย ยังไม่ได้ตั้งค่า GEMINI_API_KEY บนเซิร์ฟเวอร์ กรุณาติดต่อผู้ดูแลระบบ"

    payload = build_gemini_payload(question, chat_history)
    data = json.dumps(payload).encode('utf-8')
    last_error = None

    for model_name in gemini_candidate_models():
        url = f'{GEMINI_BASE_URL}/models/{model_name}:generateContent?key={GEMINI_API_KEY}'
        for attempt in range(2):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                text = extract_gemini_text(result)
                if text:
                    if _active_model != model_name:
                        _active_model = model_name
                        print(f"[GEMINI] ใช้โมเดล: {model_name}")
                    return text
                last_error = Exception("ไม่ได้รับข้อความตอบจาก Gemini")
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode('utf-8')
                except Exception:
                    body = str(e)
                last_error = e
                if e.code == 404:
                    print(f"[GEMINI] ข้ามโมเดล {model_name} (ไม่รองรับคีย์นี้)")
                    break
                if e.code in (429, 503) and attempt == 0:
                    print(f"[GEMINI] {model_name} ตอบ {e.code} ลองใหม่ใน 3 วินาที...")
                    time.sleep(3)
                    continue
                print(f"[GEMINI] {model_name} ข้อผิดพลาด HTTP {e.code}: {body[:200]}")
                break
            except urllib.error.URLError as e:
                last_error = e
                print(f"[GEMINI] {model_name} เชื่อมต่อไม่ได้: {e}")
                break
            except Exception as e:
                last_error = e
                print(f"[GEMINI] {model_name} ข้อผิดพลาด: {e}")
                break

    if isinstance(last_error, urllib.error.HTTPError):
        try:
            body = last_error.read().decode('utf-8')
        except Exception:
            body = str(last_error)
        return f"ขออภัย Gemini API ตอบข้อผิดพลาด (HTTP {last_error.code}): {body[:200]}"
    if isinstance(last_error, urllib.error.URLError):
        return f"ขออภัย ไม่สามารถเชื่อมต่อ Gemini API ได้: {last_error}"
    if last_error:
        return f"ขออภัย เกิดข้อผิดพลาดขณะเรียก Gemini API: {last_error}"
    return "ขออภัย ไม่สามารถเรียก Gemini API ได้ในขณะนี้ โปรดลองใหม่ภายหลัง"
