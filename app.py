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
ADMIN_DASHBOARD_KEY = os.environ.get("ADMIN_DASHBOARD_KEY", "")
USAGE_SYSTEM_USER_ID = os.environ.get("USAGE_SYSTEM_USER_ID", "__usage__")


def get_env_float(name, default):
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default

    try:
        return float(raw)
    except ValueError:
        return default


AI_INPUT_COST_PER_MTOKEN = get_env_float("AI_INPUT_COST_PER_MTOKEN", 0.115)
AI_OUTPUT_COST_PER_MTOKEN = get_env_float("AI_OUTPUT_COST_PER_MTOKEN", 0.287)
FUNCTION_REQUEST_COST_PER_MILLION = get_env_float(
    "FUNCTION_REQUEST_COST_PER_MILLION", 0.0
)
TABLESTORE_WRITE_COST_PER_10K = get_env_float("TABLESTORE_WRITE_COST_PER_10K", 0.0)

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


def estimate_ai_cost_usd(prompt_tokens, completion_tokens):
    prompt_cost = (prompt_tokens / 1000000) * AI_INPUT_COST_PER_MTOKEN
    completion_cost = (completion_tokens / 1000000) * AI_OUTPUT_COST_PER_MTOKEN
    return round(prompt_cost + completion_cost, 6)


def estimate_function_request_cost_usd(request_count):
    return round((request_count / 1000000) * FUNCTION_REQUEST_COST_PER_MILLION, 6)


def estimate_tablestore_write_cost_usd(write_count):
    if TABLESTORE_WRITE_COST_PER_10K <= 0:
        return 0.0
    return round((write_count / 10000) * TABLESTORE_WRITE_COST_PER_10K, 6)


def get_usage_meta(payload):
    usage = payload.get("usage") or {}
    prompt_tokens = int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("promptTokens")
        or 0
    )
    completion_tokens = int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("completionTokens")
        or 0
    )
    total_tokens = int(
        usage.get("total_tokens") or usage.get("totalTokens") or prompt_tokens + completion_tokens
    )
    return {
        "promptTokens": prompt_tokens,
        "completionTokens": completion_tokens,
        "totalTokens": total_tokens,
        "estimatedCostUsd": estimate_ai_cost_usd(prompt_tokens, completion_tokens),
    }


def record_usage_event(event_type, endpoint, **attrs):
    timestamp = int(time.time() * 1000)
    pk = [("uswer_id", USAGE_SYSTEM_USER_ID), ("timestamp", timestamp)]
    cols = [
        ("type", "usage_event"),
        ("eventType", event_type),
        ("endpoint", endpoint),
    ]

    for key, value in attrs.items():
        if value is None:
            continue
        cols.append((key, value))

    client.put_row(TABLE_NAME, Row(pk, cols))


def fetch_usage_rows():
    inclusive_start_pk = [("uswer_id", USAGE_SYSTEM_USER_ID), ("timestamp", 0)]
    exclusive_end_pk = [("uswer_id", USAGE_SYSTEM_USER_ID), ("timestamp", 2000000000000)]
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
                "eventType": attr.get("eventType", ""),
                "endpoint": attr.get("endpoint", ""),
                "requestKind": attr.get("requestKind", ""),
                "logType": attr.get("logType", ""),
                "model": attr.get("model", ""),
                "promptTokens": int(attr.get("promptTokens", 0) or 0),
                "completionTokens": int(attr.get("completionTokens", 0) or 0),
                "totalTokens": int(attr.get("totalTokens", 0) or 0),
                "estimatedCostUsd": float(attr.get("estimatedCostUsd", 0) or 0),
                "durationMs": int(attr.get("durationMs", 0) or 0),
                "tableWrites": int(attr.get("tableWrites", 0) or 0),
                "requestCount": int(attr.get("requestCount", 0) or 0),
                "status": attr.get("status", ""),
            }
        )

    return results


def summarize_usage_rows(rows, now_ms):
    def build_bucket(window_ms=None):
        selected = []
        for item in rows:
            if window_ms is None or now_ms - item["timestamp"] <= window_ms:
                selected.append(item)

        request_count = sum(item.get("requestCount", 0) for item in selected)
        ai_calls = sum(1 for item in selected if item.get("eventType") == "ai_call")
        write_events = sum(item.get("tableWrites", 0) for item in selected)
        ai_cost_usd = round(
            sum(float(item.get("estimatedCostUsd", 0) or 0) for item in selected), 6
        )
        return {
            "requestCount": request_count,
            "aiCallCount": ai_calls,
            "tableWriteCount": write_events,
            "promptTokens": sum(item.get("promptTokens", 0) for item in selected),
            "completionTokens": sum(
                item.get("completionTokens", 0) for item in selected
            ),
            "totalTokens": sum(item.get("totalTokens", 0) for item in selected),
            "estimatedAiCostUsd": ai_cost_usd,
            "estimatedFunctionRequestCostUsd": estimate_function_request_cost_usd(
                request_count
            ),
            "estimatedTableWriteCostUsd": estimate_tablestore_write_cost_usd(
                write_events
            ),
            "estimatedTotalCostUsd": round(
                ai_cost_usd
                + estimate_function_request_cost_usd(request_count)
                + estimate_tablestore_write_cost_usd(write_events),
                6,
            ),
        }

    latest_events = sorted(rows, key=lambda item: item["timestamp"], reverse=True)[:12]
    return {
        "last24h": build_bucket(24 * 60 * 60 * 1000),
        "last7d": build_bucket(7 * 24 * 60 * 60 * 1000),
        "allTime": build_bucket(None),
        "latestEvents": latest_events,
        "pricing": {
            "aiInputCostPerMillionTokensUsd": AI_INPUT_COST_PER_MTOKEN,
            "aiOutputCostPerMillionTokensUsd": AI_OUTPUT_COST_PER_MTOKEN,
            "functionRequestCostPerMillionUsd": FUNCTION_REQUEST_COST_PER_MILLION,
            "tableWriteCostPer10kUsd": TABLESTORE_WRITE_COST_PER_10K,
        },
    }


def get_admin_key():
    header_value = request.headers.get("X-Admin-Key", "").strip()
    if header_value:
        return header_value

    query_value = request.args.get("admin_key", "").strip()
    if query_value:
        return query_value

    data = request.get_json(silent=True) or {}
    return str(data.get("admin_key", "")).strip()


def ensure_admin_access():
    if not ADMIN_DASHBOARD_KEY:
        return json_response(
            {"error": "ADMIN_DASHBOARD_KEY is not configured on the server"}, 503
        )

    if get_admin_key() != ADMIN_DASHBOARD_KEY:
        return json_response({"error": "Admin access denied"}, 403)

    return None


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

    started_at = time.time()
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
    usage_meta = get_usage_meta(payload)
    usage_meta["durationMs"] = int((time.time() - started_at) * 1000)
    return json.loads(content), usage_meta


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

    started_at = time.time()
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
    usage_meta = get_usage_meta(payload)
    usage_meta["durationMs"] = int((time.time() - started_at) * 1000)
    return json.loads(content), usage_meta


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

            rows = fetch_user_rows(target_id)
            record_usage_event(
                "data_fetch",
                "/",
                requestKind="user_rows",
                requestCount=1,
                status="ok",
            )
            return json_response(rows)

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
            record_usage_event(
                "telegram_webhook",
                "/",
                requestKind="telegram_message",
                requestCount=1,
                tableWrites=1,
                status="ok",
            )

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
        record_usage_event(
            "log_write",
            "/api/log",
            requestKind="save_log",
            logType=log_type,
            requestCount=1,
            tableWrites=1,
            status="ok",
        )

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

        insight, usage_meta = call_qwen_insight(insight_type, context_rows)
        record_usage_event(
            "ai_call",
            "/api/ai-insight",
            requestKind=insight_type,
            model=QWEN_MODEL,
            requestCount=1,
            promptTokens=usage_meta["promptTokens"],
            completionTokens=usage_meta["completionTokens"],
            totalTokens=usage_meta["totalTokens"],
            estimatedCostUsd=usage_meta["estimatedCostUsd"],
            durationMs=usage_meta["durationMs"],
            status="ok",
        )
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
        banner, usage_meta = call_qwen_banner(weather, context_rows, user_name)
        record_usage_event(
            "ai_call",
            "/api/ai-banner",
            requestKind="daily_banner",
            model=QWEN_MODEL,
            requestCount=1,
            promptTokens=usage_meta["promptTokens"],
            completionTokens=usage_meta["completionTokens"],
            totalTokens=usage_meta["totalTokens"],
            estimatedCostUsd=usage_meta["estimatedCostUsd"],
            durationMs=usage_meta["durationMs"],
            status="ok",
        )
        banner["source"] = "qwen"
        return json_response(banner)

    except Exception as e:
        return json_response({"error": str(e)}, 500)


@app.route("/api/admin/usage-summary", methods=["GET", "OPTIONS"])
def admin_usage_summary():
    if request.method == "OPTIONS":
        return add_cors_headers(make_response())

    auth_error = ensure_admin_access()
    if auth_error:
        return auth_error

    try:
        now_ms = int(time.time() * 1000)
        usage_rows = fetch_usage_rows()
        summary = summarize_usage_rows(usage_rows, now_ms)
        summary["generatedAt"] = now_ms
        summary["model"] = QWEN_MODEL
        summary["notes"] = [
            "AI cost is estimated from response token usage.",
            "Function cost currently includes request-count estimate only.",
            "TableStore write cost is included only if TABLESTORE_WRITE_COST_PER_10K is configured.",
        ]
        return json_response(summary)
    except Exception as e:
        return json_response({"error": str(e)}, 500)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000)
