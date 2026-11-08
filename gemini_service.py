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
GEMINI_MODELS = os.getenv('GEMINI_MODELS', 'gemini-3.5-flash-lite,gemini-2.5-flash').split(",")
GEMINI_BASE_URL = os.getenv('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com/v1beta')

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
        with urllib.request.urlopen(req, timeout=float(os.getenv('GEMINI_TIMEOUT', '15'))) as resp:
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
    recent = chat_history[-int(os.getenv('GEMINI_CONTEXT_MESSAGES', '20')):]
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
        "generationConfig": {"temperature": float(os.getenv('GEMINI_TEMPERATURE', '0.7')), "maxOutputTokens": int(os.getenv('GEMINI_MAX_OUTPUT_TOKENS', '2048'))},
    }

def extract_gemini_text(result):
    candidates = result.get('candidates', [])
    if candidates:
        parts = candidates[0].get('content', {}).get('parts', [])
        if parts:
            return parts[0].get('text', 'ขออภัย ไม่สามารถตอบคำถามนี้ได้ในขณะนี้')
    return None

class GeminiError(Exception):
    """ข้อผิดพลาดที่ Agent แจ้งเฉพาะเจ้าของ (ข้อความต้องไม่มี API key)"""

def _try_models(payload, is_usable):
    """ลองทีละโมเดลพร้อม retry คืน (ผลลัพธ์, None) หรือ (None, ข้อผิดพลาดล่าสุด)"""
    global _active_model
    data = json.dumps(payload).encode('utf-8')
    last_error = None

    for model_name in gemini_candidate_models():
        url = f'{GEMINI_BASE_URL}/models/{model_name}:generateContent?key={GEMINI_API_KEY}'
        for attempt in range(int(os.getenv('GEMINI_ATTEMPTS', '2'))):
            try:
                req = urllib.request.Request(
                    url,
                    data=data,
                    headers={'Content-Type': 'application/json'},
                    method='POST'
                )
                with urllib.request.urlopen(req, timeout=float(os.getenv('GEMINI_TIMEOUT', '15'))) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                if is_usable(result):
                    if _active_model != model_name:
                        _active_model = model_name
                        print(f"[GEMINI] ใช้โมเดล: {model_name}")
                    return result, None
                print(f"[GEMINI] {model_name} ไม่ได้ส่งคำตอบที่ใช้ได้กลับมา")
                last_error = Exception("ไม่ได้รับข้อความตอบจาก Gemini")
            except urllib.error.HTTPError as e:
                try:
                    body = e.read().decode('utf-8')
                except Exception:
                    body = str(e)
                if e.code == 404:
                    # โมเดลนี้แค่ใช้กับคีย์ไม่ได้ จึงไม่ทับสาเหตุจริงจากโมเดลก่อนหน้า
                    last_error = last_error or e
                    print(f"[GEMINI] ข้ามโมเดล {model_name} (ไม่รองรับคีย์นี้)")
                    break
                last_error = e
                if e.code in (429, 503) and attempt == 0:
                    print(f"[GEMINI] {model_name} ตอบ {e.code} ลองใหม่ใน 3 วินาที...")
                    time.sleep(float(os.getenv('GEMINI_RETRY_DELAY', '3')))
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

    return None, last_error

def _model_content(result):
    candidates = result.get('candidates', [])
    content = candidates[0].get('content', {}) if candidates else {}
    return content if content.get('parts') else None

def call_gemini_with_tools(system, contents, tools):
    """เรียก Gemini แบบ function calling คืน content ของโมเดล หรือ raise GeminiError"""
    if not GEMINI_API_KEY:
        raise GeminiError("ยังไม่ได้ตั้งค่า GEMINI_API_KEY บนเซิร์ฟเวอร์")

    payload = {
        "systemInstruction": {"parts": [{"text": system}]},
        "contents": contents,
        "tools": [{"functionDeclarations": tools}],
        "generationConfig": {"temperature": float(os.getenv('GEMINI_TEMPERATURE', '0.7')), "maxOutputTokens": int(os.getenv('GEMINI_MAX_OUTPUT_TOKENS', '2048'))},
    }
    result, last_error = _try_models(payload, _model_content)
    if result is not None:
        return _model_content(result)
    if isinstance(last_error, urllib.error.HTTPError):
        if last_error.code == 429:
            raise GeminiError("โควตา Gemini หมดชั่วคราว กรุณาลองใหม่ภายหลัง")
        raise GeminiError(f"Gemini API ตอบข้อผิดพลาด (HTTP {last_error.code})")
    if isinstance(last_error, urllib.error.URLError):
        raise GeminiError("ไม่สามารถเชื่อมต่อ Gemini API ได้")
    raise GeminiError("Gemini ไม่ได้ส่งคำตอบกลับมา")

def call_gemini_api(question, chat_history):
    if not GEMINI_API_KEY:
        return "ขออภัย ยังไม่ได้ตั้งค่า GEMINI_API_KEY บนเซิร์ฟเวอร์ กรุณาติดต่อผู้ดูแลระบบ"

    payload = build_gemini_payload(question, chat_history)
    result, last_error = _try_models(payload, extract_gemini_text)
    if result is not None:
        return extract_gemini_text(result)

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
