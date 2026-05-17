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
    vision_desc: 来自 vision LLM 的精确照片描述（如果有，优先使用，把用户文字描述作为补充）
    """
    base = PLAY_PROMPT_BASE.get(play_type, PLAY_PROMPT_BASE["memorial"])
    species = PET_TYPE_HINT.get(pet_type, "a beloved pet")
    p_hint = PERSONALITY_HINT_EN.get(personality, "")
    scene_desc = SCENE_HINT_EN.get(scene, "in a warm, gentle setting")

    if vision_desc:
        # 视觉描述最权威，作为主体
        pet_desc_parts = [vision_desc.strip()]
        if extra_desc:
            pet_desc_parts.append(f'additional owner notes: "{extra_desc.strip()}"')
    else:
        # 没有视觉描述时，强调种类避免模型乱画
        species_emphatic = f"{species} (must be {species}, not any other animal)"
        pet_desc_parts = [species_emphatic]
        if extra_desc:
            pet_desc_parts.append(f'with these features: "{extra_desc.strip()}"')
    if p_hint:
        pet_desc_parts.append(p_hint)
    pet_desc = ", ".join(pet_desc_parts)

    prompt = base.format(pet_desc=pet_desc, scene_desc=scene_desc)
    prompt += ". No text, no watermark, no signature, no human face."
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


def describe_pet_photo(image_path):
    """用 vision LLM 描述宠物照片，返回英文描述（用于喂给生图模型）。失败返回 None。"""
    if not is_enabled() or not os.path.exists(image_path):
        return None
    try:
        with open(image_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        ext = image_path.rsplit(".", 1)[-1].lower()
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        text = (
            "You are helping generate a memorial portrait of someone's beloved pet. "
            "Look at this photo and write a precise visual description in 2-3 sentences, English only. "
            "Cover: species and breed, primary fur color and pattern, eye color, distinctive markings, "
            "body shape, ear shape, expression. Do NOT include any people, only describe the pet itself. "
            "Output the description directly, no preamble."
        )
        msgs = [{
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
            ],
        }]
        out = chat(msgs, model=VISION_MODEL, max_tokens=300, temperature=0.3)
        return (out or "").strip()
    except Exception as e:
        print(f"[ai.describe_pet_photo] error: {e}")
        return None


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
