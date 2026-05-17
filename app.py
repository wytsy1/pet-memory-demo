# -*- coding: utf-8 -*-
"""
毛孩子记忆馆 · 博主共创 Demo
Flask 主程序
"""
import os
import json
import time
import uuid
import secrets
from functools import wraps
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()  # 必须在 import ai/notify 之前

from flask import (
    Flask, render_template, request, redirect, url_for,
    jsonify, send_from_directory, session, flash, Response
)
from werkzeug.utils import secure_filename

import ai
import notify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
PET_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "pets")
OWNER_UPLOAD_DIR = os.path.join(UPLOAD_DIR, "owners")

SUBMISSIONS_FILE = os.path.join(DATA_DIR, "submissions.json")
CREATORS_FILE = os.path.join(DATA_DIR, "creators.json")
SAMPLES_FILE = os.path.join(DATA_DIR, "samples.json")
PETS_FILE = os.path.join(DATA_DIR, "pets.json")

ALLOWED_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


def require_admin(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not ADMIN_PASSWORD:
            return Response("ADMIN_PASSWORD env not set", 503)
        auth = request.authorization
        if not auth or auth.password != ADMIN_PASSWORD or auth.username != "admin":
            return Response(
                "需要登录", 401,
                {"WWW-Authenticate": 'Basic realm="Admin"'},
            )
        return f(*args, **kwargs)
    return wrapper


# ---------- 工具函数 ----------

def ensure_dirs():
    for d in [DATA_DIR, UPLOAD_DIR, PET_UPLOAD_DIR, OWNER_UPLOAD_DIR]:
        os.makedirs(d, exist_ok=True)
    for f, default in [
        (SUBMISSIONS_FILE, []),
        (CREATORS_FILE, []),
        (SAMPLES_FILE, []),
        (PETS_FILE, {}),
    ]:
        if not os.path.exists(f):
            with open(f, "w", encoding="utf-8") as fp:
                json.dump(default, fp, ensure_ascii=False, indent=2)


def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fp:
            return json.load(fp)
    except Exception:
        return default if default is not None else []


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)


# ---------- 宠物持久化 ----------

def load_pets():
    return load_json(PETS_FILE, default={})


def save_pets(pets):
    save_json(PETS_FILE, pets)


def get_pet(pet_id):
    return load_pets().get(pet_id)


def upsert_pet(pet_id, data):
    pets = load_pets()
    if pet_id in pets:
        pets[pet_id].update(data)
    else:
        pets[pet_id] = data
    save_pets(pets)
    return pets[pet_id]


def append_pet_field(pet_id, field, value):
    pets = load_pets()
    if pet_id not in pets:
        return None
    pets[pet_id].setdefault(field, [])
    pets[pet_id][field].append(value)
    save_pets(pets)
    return pets[pet_id]


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTS


def now_str():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def save_uploaded_files(files, target_dir, subfolder):
    saved = []
    for f in files:
        if not f or not f.filename:
            continue
        if not allowed_file(f.filename):
            continue
        ext = f.filename.rsplit(".", 1)[1].lower()
        new_name = f"{int(time.time()*1000)}_{uuid.uuid4().hex[:8]}.{ext}"
        full_path = os.path.join(target_dir, new_name)
        f.save(full_path)
        saved.append(f"uploads/{subfolder}/{new_name}")
    return saved


# ---------- 文案生成（模拟） ----------

PLAY_LABELS = {
    "aging": "我和毛孩子一起变老",
    "memorial": "再拍一张纪念合照",
    "letter": "它写给我的一封信",
    "garden": "我的电子毛孩子",
}

SCENE_HINT = {
    "家里的沙发": "客厅的沙发上有一束温柔的光",
    "窗边阳光": "窗边的阳光落在它身上",
    "公园散步": "公园里风轻轻吹过，它跑在你前面又回头看你",
    "老房子门口": "老房子门口的台阶被晒得暖暖的",
    "海边": "海风温柔地吹，浪声慢慢慢慢的",
    "记忆花园": "记忆花园里花开得安静",
}

PERSONALITY_HINT = {
    "黏人": "总是要挨着你才安心",
    "活泼": "尾巴一直摇，像小马达",
    "安静": "安安静静地陪在你旁边",
    "傲娇": "嘴上不说，眼睛却一直跟着你",
    "胆小": "把头轻轻埋进你怀里",
    "温柔": "看着你的眼神总是软软的",
}


def gen_preview_text(play_type, pet_name, owner_name, scene, personality, message):
    pet = pet_name or "毛孩子"
    owner = owner_name or "你"
    scene_line = SCENE_HINT.get(scene, "时光在你们之间慢慢流过")
    p_line = PERSONALITY_HINT.get(personality, "依然是你最熟悉的样子")

    if play_type == "aging":
        title = f"《我和{pet}一起变老》"
        body = (
            f"很多年以后，\n"
            f"{owner}坐在窗边，\n"
            f"{pet}还是喜欢趴在有阳光的地方。\n"
            f"{scene_line}。\n"
            f"它老了一点，\n"
            f"但看你的眼神还是和从前一样。"
        )
    elif play_type == "memorial":
        title = f"《和{pet}的一张纪念合照》"
        body = (
            f"{scene_line}。\n"
            f"{pet}靠在你身边，\n"
            f"{p_line}。\n"
            f"快门轻轻一按，\n"
            f"这一刻被温柔地留了下来。"
        )
    elif play_type == "letter":
        title = f"《{pet}写给{owner}的一封信》"
        body = gen_letter(pet, owner, personality, message)
    else:  # garden
        title = f"《{pet}的记忆花园》"
        body = (
            f"花园里有一小片阳光，是留给{pet}的。\n"
            f"它{p_line}。\n"
            f"今天{pet}在花园里慢慢散步，\n"
            f"风把你的名字轻轻吹过去。"
        )
    return title, body


def gen_letter(pet_name, owner_name, personality, message):
    pet = pet_name or "毛孩子"
    owner = owner_name or "你"
    p_line = PERSONALITY_HINT.get(personality, "依然是你最熟悉的样子")
    extra = ""
    if message:
        extra = f"\n你说的那句「{message}」，我也听见啦。"
    return (
        f"亲爱的{owner}：\n"
        f"我是{pet}呀。\n"
        f"今天我在有阳光的地方睡了一会儿，\n"
        f"梦见你又叫我的名字。\n"
        f"我{p_line}。\n"
        f"你不要总是难过，\n"
        f"我最喜欢你笑着看我的样子。"
        f"{extra}\n"
        f"如果你想我了，\n"
        f"就来记忆花园看看我吧。"
    )


# ---------- 路由 ----------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/play", methods=["GET"])
def play():
    play_type = request.args.get("type", "aging")
    if play_type not in PLAY_LABELS:
        play_type = "aging"
    return render_template(
        "play.html",
        play_type=play_type,
        play_label=PLAY_LABELS[play_type],
        play_labels=PLAY_LABELS,
    )


@app.route("/preview", methods=["POST"])
def preview():
    play_type = request.form.get("play_type", "aging")
    pet_name = request.form.get("pet_name", "").strip()
    pet_type = request.form.get("pet_type", "")
    personality = request.form.get("pet_personality", "")
    pet_status = request.form.get("pet_status", "")
    owner_name = request.form.get("owner_name", "").strip()
    message = request.form.get("message", "").strip()
    scene = request.form.get("scene", "")
    pet_desc = request.form.get("pet_desc", "").strip()

    pet_files = request.files.getlist("pet_photos")
    pet_paths = save_uploaded_files(pet_files, PET_UPLOAD_DIR, "pets")

    # 用 vision LLM 描述用户上传的第一张照片，作为生图 prompt 的主体
    vision_desc = None
    if pet_paths and ai.is_enabled():
        try:
            abs_first = os.path.join(BASE_DIR, pet_paths[0])
            vision_desc = ai.describe_pet_photo(abs_first)
            if vision_desc:
                print(f"[preview] vision_desc: {vision_desc[:120]}")
        except Exception as e:
            print(f"[preview] vision describe failed: {e}")

    title, body = gen_preview_text(
        play_type, pet_name, owner_name, scene, personality, message
    )

    # LLM 写宠物来信，失败降级到模板
    letter = None
    if ai.is_enabled():
        letter = ai.write_letter_llm(
            pet_name=pet_name, owner_name=owner_name, pet_type=pet_type,
            personality=personality, status=pet_status, message=message,
        )
    if not letter:
        letter = gen_letter(pet_name, owner_name, personality, message)

    # 创建/复用宠物记录
    pet_id = session.get("pet_id") or f"pet_{int(time.time()*1000)}_{uuid.uuid4().hex[:6]}"
    pet_record = {
        "id": pet_id,
        "name": pet_name or "毛孩子",
        "type": pet_type,
        "personality": personality,
        "status": pet_status,
        "owner_name": owner_name or "你",
        "scene": scene,
        "message": message,
        "pet_desc": pet_desc,
        "vision_desc": vision_desc,
        "created_at": now_str(),
        "uploaded_photos": pet_paths,
        # 不覆盖现有的 stats/messages/ai_images
    }
    existing = get_pet(pet_id) or {}
    pet_record.setdefault("stats", existing.get("stats", {"happy": 60, "company": 50, "miss": 70}))
    pet_record.setdefault("messages", existing.get("messages", []))
    pet_record.setdefault("ai_images", existing.get("ai_images", []))
    pet_record["uploaded_photos"] = list(set(existing.get("uploaded_photos", []) + pet_paths))
    upsert_pet(pet_id, pet_record)
    session["pet_id"] = pet_id

    # 提交 AI 生图任务（异步，返回 task_id 给前端轮询）
    ai_task_id = None
    ai_error = None
    if ai.is_enabled() and play_type in ("memorial", "aging", "garden"):
        try:
            prompt = ai.build_prompt(
                play_type=play_type,
                pet_type=pet_type,
                pet_name=pet_name,
                personality=personality,
                scene=scene,
                extra_desc=pet_desc,
                message=message,
                vision_desc=vision_desc,
            )
            abs_pet_paths = [os.path.join(BASE_DIR, p) for p in pet_paths] if pet_paths else None
            ai_task_id = ai.submit_generation(prompt, input_image_paths=abs_pet_paths)
            # 把 task_id 和 pet_id 绑起来，轮询完成后写入相册
            _task_to_pet[ai_task_id] = pet_id
        except Exception as e:
            ai_error = str(e)
            print(f"[preview] AI submit failed: {e}")

    session["last_preview"] = {
        "play_type": play_type,
        "pet_name": pet_name,
        "pet_type": pet_type,
        "pet_personality": personality,
        "pet_status": pet_status,
        "owner_name": owner_name,
        "message": message,
        "scene": scene,
        "pet_desc": pet_desc,
        "pet_photos": pet_paths,
    }

    return render_template(
        "preview.html",
        play_type=play_type,
        play_label=PLAY_LABELS.get(play_type, ""),
        pet_name=pet_name or "毛孩子",
        owner_name=owner_name or "你",
        title=title,
        body=body,
        letter=letter,
        scene=scene,
        ai_task_id=ai_task_id,
        ai_error=ai_error,
        ai_enabled=ai.is_enabled(),
        vision_desc=vision_desc,
        pet_id=pet_id,
    )


_task_cache = {}  # task_id -> local image url
_task_to_pet = {}  # task_id -> pet_id（用于完成后写入相册）


@app.route("/preview/poll/<task_id>")
def preview_poll(task_id):
    """前端轮询：返回任务状态。完成时返回图片 URL（已下载到本地）。"""
    if task_id in _task_cache:
        return jsonify({"status": "completed", "image_url": _task_cache[task_id]})
    try:
        import requests as rq
        url = f"{ai.BASE_URL}/tasks/{task_id}"
        resp = rq.get(url, headers={"Authorization": f"Bearer {ai.API_KEY}"}, timeout=15)
        if resp.status_code != 200:
            return jsonify({"status": "error", "message": resp.text[:200]})
        data = resp.json()
        status = data.get("status", "")
        progress = data.get("progress", 0)
        if status in ("completed", "succeeded"):
            results = data.get("results") or [r.get("url") for r in data.get("result_data", [])]
            remote_url = results[0] if results else None
            if not remote_url:
                return jsonify({"status": "error", "message": "no image url"})
            local_path = ai.download_image(remote_url, os.path.join(UPLOAD_DIR, "ai"), filename_hint="preview")
            if local_path:
                rel = os.path.relpath(local_path, BASE_DIR).replace("\\", "/")
                image_url = "/" + rel
                _task_cache[task_id] = image_url
                # 写入对应宠物的相册
                pet_id = _task_to_pet.get(task_id)
                if pet_id:
                    try:
                        append_pet_field(pet_id, "ai_images", image_url)
                    except Exception as e:
                        print(f"[poll] append_pet_field failed: {e}")
                return jsonify({"status": "completed", "image_url": image_url})
            return jsonify({"status": "completed", "image_url": remote_url})
        if status == "failed":
            return jsonify({"status": "failed", "message": str(data.get("error", "failed"))})
        return jsonify({"status": "processing", "progress": progress})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/garden")
def garden_redirect():
    pet_id = session.get("pet_id")
    if pet_id and get_pet(pet_id):
        return redirect(url_for("garden", pet_id=pet_id))
    flash("先去玩法页创建一只毛孩子吧～")
    return redirect(url_for("play"))


@app.route("/garden/<pet_id>")
def garden(pet_id):
    pet = get_pet(pet_id)
    if not pet:
        flash("找不到这只毛孩子的记忆花园，去创建一个吧～")
        return redirect(url_for("play"))
    share_url = request.host_url.rstrip("/") + url_for("garden", pet_id=pet_id)
    return render_template("garden.html", pet=pet, share_url=share_url)


@app.route("/garden/<pet_id>/chat", methods=["POST"])
def garden_chat(pet_id):
    pet = get_pet(pet_id)
    if not pet:
        return jsonify({"error": "pet not found"}), 404
    data = request.get_json(silent=True) or {}
    user_message = (data.get("message") or "").strip()
    if not user_message:
        return jsonify({"error": "empty message"}), 400

    history = pet.get("chat_history", [])
    reply = ai.chat_with_pet(pet, user_message, history=history)

    # 追加到历史，截断保留最近 40 条（即 20 轮）
    pets = load_pets()
    p = pets.get(pet_id)
    if p is not None:
        ch = p.setdefault("chat_history", [])
        ch.append({"role": "user", "text": user_message, "at": now_str()})
        ch.append({"role": "pet", "text": reply, "at": now_str()})
        p["chat_history"] = ch[-40:]
        # 聊天本身也算"陪伴" → 略微提升数值
        st = p.setdefault("stats", {"happy": 60, "company": 50, "miss": 70})
        st["happy"] = min(100, st.get("happy", 60) + 3)
        st["company"] = min(100, st.get("company", 50) + 5)
        st["miss"] = max(0, st.get("miss", 70) - 2)
        save_pets(pets)

    return jsonify({"reply": reply, "stats": p.get("stats") if p else None})


@app.route("/garden/<pet_id>/chat/history", methods=["GET"])
def garden_chat_history(pet_id):
    pet = get_pet(pet_id)
    if not pet:
        return jsonify({"history": []})
    return jsonify({"history": pet.get("chat_history", [])})


@app.route("/garden/<pet_id>/act", methods=["POST"])
def garden_act(pet_id):
    pet = get_pet(pet_id)
    if not pet:
        return jsonify({"error": "pet not found"}), 404
    data = request.get_json(silent=True) or {}
    action = data.get("action", "")
    text_msg = (data.get("message") or "").strip()
    name = pet.get("name", "毛孩子")
    feedback_map = {
        "feed": (f"{name}开心地吃了起来。", {"happy": 8, "company": 4, "miss": -2}),
        "pet": (f"{name}眯起眼睛蹭了蹭你。", {"happy": 6, "company": 6, "miss": -3}),
        "play": (f"你陪{name}玩了一会儿，它尾巴摇得很开心。", {"happy": 10, "company": 10, "miss": -5}),
        "say": (f"{name}静静地听完了你想说的话。", {"happy": 4, "company": 8, "miss": -4}),
    }
    text, delta = feedback_map.get(action, (f"{name}看了你一眼。", {"happy": 1, "company": 1, "miss": 0}))

    pets = load_pets()
    p = pets.get(pet_id)
    if not p:
        return jsonify({"error": "pet not found"}), 404
    stats = p.setdefault("stats", {"happy": 60, "company": 50, "miss": 70})
    for k, v in delta.items():
        stats[k] = max(0, min(100, stats.get(k, 50) + v))
    if action == "say" and text_msg:
        p.setdefault("messages", []).insert(0, {
            "text": text_msg,
            "at": now_str(),
        })
        # 最多保留 50 条
        p["messages"] = p["messages"][:50]
    save_pets(pets)
    return jsonify({"text": text, "delta": delta, "stats": stats})


@app.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "GET":
        prefill = session.get("last_preview", {})
        return render_template("submit.html", prefill=prefill, play_labels=PLAY_LABELS)

    # POST
    pet_files = request.files.getlist("pet_photos")
    owner_files = request.files.getlist("owner_photos")
    # 先读字节用于邮件附件（save_uploaded_files 会消费 stream）
    pet_bytes_for_mail = []
    for f in pet_files[:5]:
        if f and f.filename:
            data = f.read()
            f.seek(0)
            pet_bytes_for_mail.append((f.filename, data))
    pet_paths = save_uploaded_files(pet_files, PET_UPLOAD_DIR, "pets")
    owner_paths = save_uploaded_files(owner_files, OWNER_UPLOAD_DIR, "owners")

    sub = {
        "id": f"sub_{int(time.time()*1000)}",
        "created_at": now_str(),
        "play_type": request.form.get("play_type", ""),
        "pet_name": request.form.get("pet_name", "").strip(),
        "pet_type": request.form.get("pet_type", ""),
        "pet_status": request.form.get("pet_status", ""),
        "pet_personality": request.form.get("pet_personality", ""),
        "owner_name": request.form.get("owner_name", "").strip(),
        "contact": request.form.get("contact", "").strip(),
        "creator_source": request.form.get("creator_source", "").strip(),
        "message": request.form.get("message", "").strip(),
        "want_package": request.form.get("want_package", ""),
        "pet_photos": pet_paths,
        "owner_photos": owner_paths,
        "allow_showcase": request.form.get("allow_showcase", "") == "yes",
        "order_status": "新提交",
        "payment_status": "未付款",
        "commission_amount": 0,
    }

    subs = load_json(SUBMISSIONS_FILE)
    subs.append(sub)
    save_json(SUBMISSIONS_FILE, subs)

    # 邮件通知（带宠物照附件，作为兜底防止免费空间数据丢失）
    try:
        notify.notify_submission(sub, pet_photo_files=pet_bytes_for_mail)
    except Exception as e:
        print(f"[submit] notify failed: {e}")

    return redirect(url_for("success"))


@app.route("/success")
def success():
    pet_name = session.get("last_preview", {}).get("pet_name", "毛孩子")
    return render_template("success.html", pet_name=pet_name)


@app.route("/creator", methods=["GET", "POST"])
def creator():
    if request.method == "GET":
        return render_template("creator.html")
    item = {
        "id": f"creator_{int(time.time()*1000)}",
        "created_at": now_str(),
        "nickname": request.form.get("nickname", "").strip(),
        "platform": request.form.get("platform", ""),
        "profile_url": request.form.get("profile_url", "").strip(),
        "followers": request.form.get("followers", "").strip(),
        "contact": request.form.get("contact", "").strip(),
        "wants_sample": request.form.get("wants_sample", "") == "yes",
        "status": "待联系",
    }
    creators = load_json(CREATORS_FILE)
    creators.append(item)
    save_json(CREATORS_FILE, creators)
    try:
        notify.notify_creator(item)
    except Exception as e:
        print(f"[creator] notify failed: {e}")
    flash("申请已提交，我们会尽快联系你～")
    return redirect(url_for("creator"))


@app.route("/admin")
@require_admin
def admin():
    subs = load_json(SUBMISSIONS_FILE)
    creators = load_json(CREATORS_FILE)
    # 倒序展示
    subs = list(reversed(subs))
    creators = list(reversed(creators))

    # 简单统计
    play_stat = {}
    for s in subs:
        k = PLAY_LABELS.get(s.get("play_type", ""), s.get("play_type", "未知"))
        play_stat[k] = play_stat.get(k, 0) + 1

    creator_stat = {}
    for s in subs:
        src = s.get("creator_source") or "（无来源）"
        creator_stat[src] = creator_stat.get(src, 0) + 1

    return render_template(
        "admin.html",
        submissions=subs,
        creators=creators,
        play_stat=play_stat,
        creator_stat=creator_stat,
        play_labels=PLAY_LABELS,
    )


@app.route("/uploads/<path:filename>")
def uploaded_file(filename):
    return send_from_directory(UPLOAD_DIR, filename)


# ---------- 启动 ----------

ensure_dirs()

if __name__ == "__main__":
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    port = int(os.getenv("PORT", "8503"))
    host = os.getenv("HOST", "127.0.0.1")
    app.run(host=host, port=port, debug=debug)
