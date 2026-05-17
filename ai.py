# -*- coding: utf-8 -*-
"""
AI 生图模块
- 兼容 aicodewith 异步任务接口
- 支持纯文生图（gpt-image-2）和图生图（gemini-3-pro-image-preview）
- 失败自动降级到 SVG 占位
"""
import os
import time
import json
import base64
import requests
from urllib.parse import urljoin

BASE_URL = os.getenv("AI_BASE_URL", "https://api.aicodewith.com/v1").rstrip("/")
API_KEY = os.getenv("AI_API_KEY", "").strip()
IMAGE_MODEL = os.getenv("AI_IMAGE_MODEL", "gpt-image-2").strip()
SUPPORTS_INPUT = os.getenv("AI_IMAGE_SUPPORTS_INPUT", "false").lower() == "true"

POLL_TIMEOUT = 180  # 单次任务最长等待秒数
POLL_INTERVAL = 4

TEXT_MODEL = os.getenv("AI_TEXT_MODEL", "claude-haiku-4-5-20251001")
VISION_MODEL = os.getenv("AI_VISION_MODEL", "claude-haiku-4-5-20251001")


# ---------- Prompt 构建 ----------

PLAY_PROMPT_BASE = {
    "memorial": (
        "A warm, photorealistic memorial photo of {pet_desc}, "
        "{scene_desc}, soft natural light, intimate emotional atmosphere, "
        "shot on Sony A7 with 50mm lens, shallow depth of field, "
        "film grain, gentle color palette in cream and warm tones, "
        "high detail on fur texture and eyes, looks like a tender family photo"
    ),
    "aging": (
        "A heartwarming photorealistic image of {pet_desc} as an elderly version, "
        "with subtle signs of age — slightly graying fur around the muzzle, "
        "calm and wise eyes, {scene_desc}, soft warm afternoon light, "
        "shot on Canon R5 with 85mm lens, gentle bokeh, "
        "cinematic emotional mood, cream and amber tones, "
        "looks like a quiet family memory"
    ),
    "garden": (
        "A serene photorealistic scene of {pet_desc} resting peacefully in a "
        "sunlit memorial garden, soft pastel flowers around, golden hour light, "
        "warm cream color palette, shot on 50mm lens with shallow depth of field, "
        "tender and tranquil mood, {scene_desc}"
    ),
}

PET_TYPE_HINT = {
    "猫": "a cat",
    "狗": "a dog",
    "其他": "a beloved pet",
}

PERSONALITY_HINT_EN = {
    "黏人": "with affectionate, attached eyes looking at the viewer",
    "活泼": "looking lively, with bright spirited eyes",
    "安静": "calm and quiet, peaceful expression",
    "傲娇": "with a slightly aloof but soft expression",
    "胆小": "gentle and timid, curled up softly",
    "温柔": "with the softest, kindest eyes",
}

SCENE_HINT_EN = {
    "家里的沙发": "lying on a cozy beige sofa in a sunlit living room",
    "窗边阳光": "sitting by a window with warm sunlight falling on its fur",
    "公园散步": "in a soft-focus green park, gentle breeze",
    "老房子门口": "on the stone step of an old quiet home, late afternoon light",
    "海边": "by a calm seaside at dusk, soft wind, gentle waves",
    "记忆花园": "in a dreamy memorial garden with soft pastel flowers",
}


def build_prompt(play_type, pet_type, pet_name, personality, scene, extra_desc, message, vision_desc=None):
    """构造图像生成 prompt。
    vision_desc: 来自 vision LLM 的多轮精确描述（最高优先级，作为主体）
    """
    species = PET_TYPE_HINT.get(pet_type, "a beloved pet")
    p_hint = PERSONALITY_HINT_EN.get(personality, "")
    scene_desc = SCENE_HINT_EN.get(scene, "in a warm, gentle setting")

    # 风格 + 镜头（每种玩法不同氛围）
    style_map = {
        "memorial": (
            "Style: warm photorealistic memorial portrait, soft natural light, intimate emotional atmosphere, "
            "shot on Sony A7 with 50mm lens at f/1.8, shallow depth of field, subtle film grain, "
            "gentle cream and warm tones, high detail on fur texture and eyes, looks like a tender family photo."
        ),
        "aging": (
            "Style: heartwarming photorealistic portrait of an elderly version of this pet — "
            "subtle signs of age (slightly graying fur around the muzzle, calm wise eyes), "
            "soft warm afternoon light, shot on Canon R5 with 85mm lens at f/2, gentle bokeh, "
            "cinematic emotional mood, cream and amber tones."
        ),
        "garden": (
            "Style: serene photorealistic scene, the pet resting peacefully in a sunlit memorial garden, "
            "soft pastel flowers around, golden hour light, warm cream palette, 50mm lens, shallow depth of field, "
            "tender and tranquil mood."
        ),
    }
    style = style_map.get(play_type, style_map["memorial"])

    # 主体描述：优先用 vision 多段输出
    if vision_desc:
        subject = (
            "PET TO RECREATE (extremely faithful reproduction required):\n"
            f"{vision_desc.strip()}\n\n"
            "Use every detail above. Match the exact fur color, pattern, eye color, markings, "
            "ear shape, and any distinctive features. The result should look like the SAME individual pet."
        )
        if extra_desc:
            subject += f'\n\nOwner-provided extra notes: "{extra_desc.strip()}"'
    else:
        subject = (
            f"Subject: {species} (strictly a {species}, not any other animal). "
            + (f'Owner-described features: "{extra_desc.strip()}". ' if extra_desc else "")
            + (p_hint if p_hint else "")
        )

    scene_line = f"Scene: {scene_desc}."
    constraints = (
        "Constraints: photorealistic, no humans visible, no text, no watermark, no signature, "
        "no captions, only the pet as described, frame the pet centered, eyes clearly visible."
    )

    prompt = "\n\n".join([subject, scene_line, style, constraints])
    return prompt


# ---------- API 调用 ----------

def is_enabled():
    return bool(API_KEY)


def _post(path, payload=None, files=None, data=None):
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    if payload is not None:
        headers["Content-Type"] = "application/json"
        return requests.post(url, headers=headers, json=payload, timeout=60)
    return requests.post(url, headers=headers, files=files, data=data, timeout=60)


def _get(path):
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    return requests.get(url, headers=headers, timeout=30)


def submit_generation(prompt, input_image_paths=None, size="1024x1024"):
    """提交一个图像生成任务，返回 task_id。
    input_image_paths: 本地图片路径列表（仅当 SUPPORTS_INPUT=True 时使用）
    """
    payload = {
        "model": IMAGE_MODEL,
        "prompt": prompt,
        "n": 1,
        "size": size,
    }
    if SUPPORTS_INPUT and input_image_paths:
        # base64 编码本地图片，传 images 数组
        imgs = []
        for p in input_image_paths[:3]:  # 最多 3 张
            if not os.path.exists(p):
                continue
            with open(p, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
            ext = p.rsplit(".", 1)[-1].lower()
            mime = "jpeg" if ext in ("jpg", "jpeg") else ext
            imgs.append(f"data:image/{mime};base64,{b64}")
        if imgs:
            payload["images"] = imgs

    resp = _post("/images/generations", payload=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"submit failed [{resp.status_code}]: {resp.text[:300]}")
    data = resp.json()
    task_id = data.get("id")
    if not task_id:
        raise RuntimeError(f"no task id in response: {data}")
    return task_id


def poll_task(task_id, timeout=POLL_TIMEOUT):
    start = time.time()
    while time.time() - start < timeout:
        resp = _get(f"/tasks/{task_id}")
        if resp.status_code != 200:
            time.sleep(POLL_INTERVAL)
            continue
        data = resp.json()
        status = data.get("status", "")
        if status in ("completed", "succeeded"):
            results = data.get("results") or [r.get("url") for r in data.get("result_data", [])]
            return [u for u in results if u]
        if status == "failed":
            raise RuntimeError(f"task failed: {data.get('error') or data}")
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"task {task_id} timeout after {timeout}s")


def generate_image(prompt, input_image_paths=None, size="1024x1024", timeout=POLL_TIMEOUT):
    """同步生成一张图，返回图片 URL。失败返回 None。"""
    if not is_enabled():
        return None
    try:
        task_id = submit_generation(prompt, input_image_paths=input_image_paths, size=size)
        urls = poll_task(task_id, timeout=timeout)
        return urls[0] if urls else None
    except Exception as e:
        print(f"[ai.generate_image] error: {e}")
        return None


def chat(messages, model=None, max_tokens=600, temperature=0.7):
    """通用 chat 接口。失败抛异常。"""
    payload = {
        "model": model or TEXT_MODEL,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": messages,
    }
    resp = _post("/chat/completions", payload=payload)
    if resp.status_code != 200:
        raise RuntimeError(f"chat failed [{resp.status_code}]: {resp.text[:300]}")
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _image_msg(image_path, text):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    ext = image_path.rsplit(".", 1)[-1].lower()
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    return [{
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
        ],
    }]


def describe_pet_photo(image_path):
    """多轮 vision 调用，从不同角度提取细节，组装成超精细英文描述。
    返回单个字符串，已经是组装好的可直接放入图像 prompt 的描述。
    """
    if not is_enabled() or not os.path.exists(image_path):
        return None

    # ---- Pass 1: 结构化基础特征 ----
    p1 = (
        "You are an expert pet identification AI helping create a faithful portrait. "
        "Examine the pet in this photo and output STRICTLY in this format, English only, "
        "one line per field, no extra commentary:\n"
        "SPECIES: [cat|dog|other - be specific]\n"
        "BREED: [most likely breed or mix; if unclear say 'mixed-breed' with closest match]\n"
        "BUILD: [body size and shape: slim/medium/chunky; proportions]\n"
        "AGE_LOOK: [kitten/puppy/young/adult/senior - based on visible features]\n"
        "PRIMARY_COLOR: [main fur color, use specific names like 'ginger orange', 'cream', 'jet black', 'silver tabby']\n"
        "PATTERN: [solid|tabby|tuxedo|bicolor|tricolor|spotted|brindle|etc., describe distribution]\n"
        "EYE_COLOR: [be specific: amber, copper, emerald green, sky blue, hazel, etc.]\n"
        "EAR_SHAPE: [erect triangular / folded / floppy / pricked / etc.]\n"
        "DISTINCTIVE_MARKS: [list any unique markings: white chest patch, ear notch, scar, "
        "asymmetric patches, blaze on forehead, white socks on N paws, etc. Be precise about LOCATION.]"
    )

    # ---- Pass 2: 面部细节 + 表情 ----
    p2 = (
        "Focus ONLY on this pet's face. In one paragraph (60-100 words, English), describe in extreme "
        "detail: eye shape and exact color, eye expression (alert/sleepy/curious/calm), nose color and "
        "shape, mouth position, whisker visibility, fur on the face (any color variations around eyes, "
        "muzzle, forehead), and any markings ONLY on the face. Be precise and visual; this will be used "
        "by an AI image generator. Do not describe surroundings."
    )

    parts = {}
    try:
        out1 = chat(_image_msg(image_path, p1), model=VISION_MODEL, max_tokens=400, temperature=0.2)
        parts["structured"] = (out1 or "").strip()
    except Exception as e:
        print(f"[describe_pet_photo p1] {e}")
    try:
        out2 = chat(_image_msg(image_path, p2), model=VISION_MODEL, max_tokens=300, temperature=0.3)
        parts["face"] = (out2 or "").strip()
    except Exception as e:
        print(f"[describe_pet_photo p2] {e}")

    if not parts:
        return None

    # 组装：结构化字段在前（明确细节），自然段在后（氛围）
    composed = []
    if "structured" in parts:
        composed.append("Pet identification:\n" + parts["structured"])
    if "face" in parts:
        composed.append("Face details:\n" + parts["face"])
    return "\n\n".join(composed)


def write_letter_llm(pet_name, owner_name, pet_type, personality, status, message):
    """用 LLM 写一封温柔的宠物来信。失败返回 None（调用方降级到模板）。"""
    if not is_enabled():
        return None
    try:
        sys = (
            "你是一位温柔的中文写作者，正在以一只宠物的口吻给它的主人写一封短信。"
            "信件要求：\n"
            "- 用中文，第一人称（以宠物口吻），称呼主人为给定的名字\n"
            "- 100-180 字，温柔、治愈、不煽情、不要悲伤词\n"
            "- 不要出现「复活」「灵魂」「重生」「离开」「死亡」等敏感词\n"
            "- 可以描写一个具体的画面：阳光、窗台、毛毯、零食、追蝴蝶等\n"
            "- 结尾自然，不必每次说『我爱你』\n"
            "- 直接输出信件内容，不要前后缀解释"
        )
        user = (
            f"宠物名字：{pet_name or '小宝贝'}\n"
            f"宠物类型：{pet_type or '宠物'}\n"
            f"宠物性格：{personality or '温柔'}\n"
            f"宠物状态：{status or '陪伴中'}\n"
            f"主人昵称：{owner_name or '你'}\n"
            f"主人想说的话：{message or '（没填）'}\n\n"
            "请写一封温柔的信。"
        )
        msgs = [
            {"role": "user", "content": sys + "\n\n---\n\n" + user},
        ]
        out = chat(msgs, model=TEXT_MODEL, max_tokens=500, temperature=0.85)
        return (out or "").strip()
    except Exception as e:
        print(f"[ai.write_letter_llm] error: {e}")
        return None


def download_image(url, save_dir, filename_hint="ai"):
    """把远程图下载到本地，返回本地相对路径（uploads/ai/xxx.png）。"""
    try:
        os.makedirs(save_dir, exist_ok=True)
        headers = {"Authorization": f"Bearer {API_KEY}"}
        resp = requests.get(url, headers=headers, timeout=60)
        if resp.status_code != 200:
            return None
        ext = "png"
        if "." in url.split("?")[0].rsplit("/", 1)[-1]:
            ext = url.split("?")[0].rsplit(".", 1)[-1].lower()
            if ext not in ("png", "jpg", "jpeg", "webp"):
                ext = "png"
        name = f"{int(time.time()*1000)}_{filename_hint}.{ext}"
        path = os.path.join(save_dir, name)
        with open(path, "wb") as f:
            f.write(resp.content)
        return path
    except Exception as e:
        print(f"[ai.download_image] error: {e}")
        return None
