from flask import Flask, request, make_response
import json
import os
import time
import requests
from tablestore import OTSClient, Row

app = Flask(__name__)

ACCESS_KEY_ID = os.environ["ACCESS_KEY_ID"]
ACCESS_KEY_SECRET = os.environ["ACCESS_KEY_SECRET"]
INSTANCE_NAME = os.environ["INSTANCE_NAME"]
ENDPOINT = os.environ["ENDPOINT"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
TABLE_NAME = os.environ.get("TABLE_NAME", "wellness_logs")
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
QWEN_MODEL = os.environ.get("QWEN_MODEL", "qwen-plus")
QWEN_BASE_URL = os.environ.get(
    "QWEN_BASE_URL",
    "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions",
)
ADMIN_TELEGRAM_CHAT_ID = os.environ.get("ADMIN_TELEGRAM_CHAT_ID", "")

client = OTSClient(ENDPOINT, ACCESS_KEY_ID, ACCESS_KEY_SECRET, INSTANCE_NAME)


def add_cors_headers(resp):
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp


def json_response(payload, status=200):
    resp = make_response(json.dumps(payload, ensure_ascii=False), status)
    resp.headers["Content-Type"] = "application/json; charset=utf-8"
    return add_cors_headers(resp)


def fetch_user_rows(user_id):
    inclusive_start_pk = [("uswer_id", str(user_id)), ("timestamp", 0)]
    exclusive_end_pk = [("uswer_id", str(user_id)), ("timestamp", 2000000000000)]
    _, _, row_list, _ = client.get_range(
        TABLE_NAME,
        "FORWARD",
        inclusive_start_pk,
        exclusive_end_pk,
    )

    results = []
    for row in row_list:
        attr = {col[0]: col[1] for col in row.attribute_columns}
        results.append(
            {
                "timestamp": row.primary_key[1][1],
                "caffeine": attr.get("caffeine", 0),
                "sugar": attr.get("sugar", 0),
                "text": attr.get("text", ""),
                "type": attr.get("type", "telegram"),
                "mood": attr.get("mood"),
                "note": attr.get("note", ""),
                "sleep": attr.get("sleep"),
                "sleepScore": attr.get("sleepScore"),
                "rhr": attr.get("rhr"),
                "caffeineGoal": attr.get("caffeineGoal"),
                "sugarGoal": attr.get("sugarGoal"),
                "exercise": attr.get("exercise", ""),
                "alcohol": attr.get("alcohol", ""),
                "nap": attr.get("nap", ""),
                "quickSleepQuality": attr.get("quickSleepQuality", ""),
                "quickSleepBand": attr.get("quickSleepBand", ""),
                "quickCaffeinePlan": attr.get("quickCaffeinePlan", ""),
                "quickSugarPlan": attr.get("quickSugarPlan", ""),
                "quickAlcoholImpact": attr.get("quickAlcoholImpact", ""),
                "feedbackCategory": attr.get("feedbackCategory", ""),
            }
        )

    return results


def build_ai_context(rows, insight_type):
    by_date = {}
    for item in rows:
        date_str = time.strftime("%Y-%m-%d", time.localtime(item["timestamp"] / 1000))
        if date_str not in by_date:
            by_date[date_str] = {
                "morning": {},
                "caffeine": 0,
                "sugar": 0,
                "entryCount": 0,
                "entryTexts": [],
            }

        if item.get("type") == "morning":
            by_date[date_str]["morning"] = {
                "sleep": item.get("sleep"),
                "mood": item.get("mood"),
                "sleepScore": item.get("sleepScore"),
                "rhr": item.get("rhr"),
                "caffeineGoal": item.get("caffeineGoal"),
                "sugarGoal": item.get("sugarGoal"),
                "exercise": item.get("exercise"),
                "alcohol": item.get("alcohol"),
                "nap": item.get("nap"),
                "note": item.get("note", ""),
            }
        elif item.get("type") in ("entry", "telegram"):
            by_date[date_str]["caffeine"] += item.get("caffeine", 0) or 0
            by_date[date_str]["sugar"] += item.get("sugar", 0) or 0
            by_date[date_str]["entryCount"] += 1
            if item.get("text"):
                entry_text = item["text"]
                if item.get("note"):
                    entry_text = f"{entry_text} | {item['note']}"
                by_date[date_str]["entryTexts"].append(entry_text)

    dates = sorted(by_date.keys())
    recent_dates = dates[-7:] if insight_type == "daily" else dates[-14:]
    return [{"date": d, **by_date[d]} for d in recent_dates]


def call_qwen_insight(insight_type, context_rows):
    system_prompt = (
        "You are a concise wellness coach for a caffeine-sensitive user. "
        "Use only the provided data. Do not diagnose. "
        "Return JSON with keys: title, body, focus. "
        "Keep title under 28 Korean characters and body under 120 Korean characters. "
        "Focus should be one of: caffeine, sleep, sugar, recovery, trend."
    )

    if insight_type == "daily":
        user_prompt = (
            "Create one gentle morning insight for today's planning. "
            "Mention only the most useful pattern from recent sleep, caffeine, sugar, exercise, alcohol, nap, meal pattern, or mood data.\n"
            f"Data: {json.dumps(context_rows, ensure_ascii=False)}"
        )
    else:
        user_prompt = (
            "Create one short weekly trend insight. "
            "Highlight one repeated pattern the user may want to test next week, including meal pattern if relevant.\n"
            f"Data: {json.dumps(context_rows, ensure_ascii=False)}"
        )

    response = requests.post(
        QWEN_BASE_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        },
        json={
            "model": QWEN_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.4,
            "max_tokens": 220,
            "stream": False,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return json.loads(content)


def call_qwen_banner(weather, context_rows, user_name):
    system_prompt = (
        "You write a short Korean wellness banner message for a caffeine-sensitive user. "
        "Use weather plus recent habit context. Do not diagnose. "
        "Return JSON with keys: morning_greeting, afternoon_greeting, evening_greeting, night_greeting, message. "
        "Each greeting should feel warm and natural, under 28 Korean characters. "
        "Message should be under 70 Korean characters."
    )

    user_prompt = (
        "Create four greeting lines for different times of day and one short banner line for today's weather area. "
        "Use the user's first name naturally if provided. It should feel warm, practical, and lightly coaching.\n"
        f"User name: {user_name}\n"
        f"Weather: {json.dumps(weather, ensure_ascii=False)}\n"
        f"Recent data: {json.dumps(context_rows, ensure_ascii=False)}"
    )

    response = requests.post(
        QWEN_BASE_URL,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        },
        json={
            "model": QWEN_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.5,
            "max_tokens": 120,
            "stream": False,
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    content = payload["choices"][0]["message"]["content"]
    return json.loads(content)


def notify_admin_feedback(category, text, user_id):
    if not ADMIN_TELEGRAM_CHAT_ID:
        return

    label_map = {
        "good": "좋았어요",
        "bug": "불편했어요",
        "idea": "기능 제안",
    }
    message = (
        "[웰니스 로그 피드백]\n"
        f"유형: {label_map.get(category, category)}\n"
        f"사용자: {user_id}\n"
        f"내용: {text}"
    )
    reply_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(
        reply_url,
        json={"chat_id": ADMIN_TELEGRAM_CHAT_ID, "text": message},
        timeout=10,
    )


@app.route("/", methods=["GET", "POST", "OPTIONS"])
def telegram_webhook():
    if request.method == "OPTIONS":
        return add_cors_headers(make_response())

    if request.method == "GET":
        try:
            target_id = request.args.get("user_id")

            if not target_id:
                return json_response({"error": "User ID is required"}, 400)

            return json_response(fetch_user_rows(target_id))

        except Exception as e:
            return f"Server Error: {str(e)}", 500

    try:
        data = request.get_json(force=True, silent=True)

        if data and "message" in data:
            chat_id = str(data["message"]["chat"]["id"])
            text = data["message"].get("text", "")

            caffeine = 150 if "커피" in text else 0
            sugar = 10 if ("단거" in text or "초코" in text) else 0

            pk = [("uswer_id", chat_id), ("timestamp", int(time.time() * 1000))]
            cols = [
                ("text", text),
                ("caffeine", caffeine),
                ("sugar", sugar),
                ("type", "telegram"),
                ("mood", 7),
                ("note", ""),
            ]

            client.put_row(TABLE_NAME, Row(pk, cols))

            reply_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(
                reply_url,
                json={
                    "chat_id": chat_id,
                    "text": f"✅ 기록 완료! ({caffeine}mg)",
                },
            )

    except Exception as e:
        print(f"Post Error: {e}")

    return "OK", 200


@app.route("/api/log", methods=["POST", "OPTIONS"])
def save_web_log():
    if request.method == "OPTIONS":
        return add_cors_headers(make_response())

    try:
        data = request.get_json(force=True)
        user_id = str(data.get("user_id", "")).strip()

        if not user_id:
            return json_response({"error": "user_id is required"}, 400)

        timestamp = int(data.get("timestamp") or time.time() * 1000)
        log_type = data.get("type", "entry")
        text = data.get("text", "")
        caffeine = int(data.get("caffeine", 0) or 0)
        sugar = int(data.get("sugar", 0) or 0)
        mood = int(data.get("mood", 0) or 0)
        note = data.get("note", "")

        cols = [
            ("type", log_type),
            ("text", text),
            ("caffeine", caffeine),
            ("sugar", sugar),
            ("mood", mood),
            ("note", note),
        ]

        if log_type == "morning":
            cols.extend(
                [
                    ("sleep", float(data.get("sleep", 0) or 0)),
                    ("sleepScore", int(data.get("sleepScore", 0) or 0)),
                    ("rhr", int(data.get("rhr", 0) or 0)),
                    ("caffeineGoal", int(data.get("caffeineGoal", 150) or 150)),
                    ("sugarGoal", int(data.get("sugarGoal", 30) or 30)),
                    ("exercise", data.get("exercise", "")),
                    ("alcohol", data.get("alcohol", "")),
                    ("nap", data.get("nap", "")),
                    ("quickSleepQuality", data.get("quickSleepQuality", "")),
                    ("quickSleepBand", data.get("quickSleepBand", "")),
                    ("quickCaffeinePlan", data.get("quickCaffeinePlan", "")),
                    ("quickSugarPlan", data.get("quickSugarPlan", "")),
                    ("quickAlcoholImpact", data.get("quickAlcoholImpact", "")),
                ]
            )
        elif log_type == "feedback":
            cols.extend(
                [
                    ("feedbackCategory", data.get("feedbackCategory", "")),
                ]
            )

        pk = [("uswer_id", user_id), ("timestamp", timestamp)]
        client.put_row(TABLE_NAME, Row(pk, cols))

        if log_type == "feedback":
            notify_admin_feedback(data.get("feedbackCategory", ""), text, user_id)

        return json_response({"ok": True, "timestamp": timestamp})

    except Exception as e:
        return json_response({"error": str(e)}, 500)


@app.route("/api/ai-insight", methods=["GET", "OPTIONS"])
def ai_insight():
    if request.method == "OPTIONS":
        return add_cors_headers(make_response())

    if not DASHSCOPE_API_KEY:
        return json_response({"error": "Qwen API key is not configured"}, 503)

    try:
        user_id = request.args.get("user_id")
        insight_type = request.args.get("type", "daily")

        if not user_id:
            return json_response({"error": "user_id is required"}, 400)

        if insight_type not in ("daily", "weekly"):
            return json_response({"error": "type must be daily or weekly"}, 400)

        rows = fetch_user_rows(user_id)
        context_rows = build_ai_context(rows, insight_type)

        if not context_rows:
            return json_response(
                {
                    "title": "기록이 더 필요합니다",
                    "body": "아직 AI가 읽을 데이터가 충분하지 않습니다. 며칠만 더 기록해보세요.",
                    "focus": "trend",
                    "source": "fallback",
                }
            )

        insight = call_qwen_insight(insight_type, context_rows)
        insight["source"] = "qwen"
        return json_response(insight)

    except Exception as e:
        return json_response({"error": str(e)}, 500)


@app.route("/api/ai-banner", methods=["POST", "OPTIONS"])
def ai_banner():
    if request.method == "OPTIONS":
        return add_cors_headers(make_response())

    if not DASHSCOPE_API_KEY:
        return json_response({"error": "Qwen API key is not configured"}, 503)

    try:
        data = request.get_json(force=True)
        user_id = data.get("user_id")
        weather = data.get("weather", {})
        user_name = data.get("user_name", "")

        if not user_id:
            return json_response({"error": "user_id is required"}, 400)

        rows = fetch_user_rows(user_id)
        context_rows = build_ai_context(rows, "daily")
        banner = call_qwen_banner(weather, context_rows, user_name)
        banner["source"] = "qwen"
        return json_response(banner)

    except Exception as e:
        return json_response({"error": str(e)}, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000)
