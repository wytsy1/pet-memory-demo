# -*- coding: utf-8 -*-
"""
邮件通知模块
配置环境变量：
  SMTP_HOST          smtp.qq.com
  SMTP_PORT          465
  SMTP_USER          你的QQ邮箱（如 xxx@qq.com）
  SMTP_PASSWORD      QQ邮箱SMTP授权码（不是登录密码）
  NOTIFY_TO          接收通知的邮箱（可以和 SMTP_USER 相同）
"""
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.qq.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
NOTIFY_TO = os.getenv("NOTIFY_TO", SMTP_USER).strip()


def is_enabled():
    return bool(SMTP_USER and SMTP_PASSWORD and NOTIFY_TO)


def send_mail(subject, body_html, attachments=None):
    """attachments: list of (filename, bytes, mime) tuples"""
    if not is_enabled():
        print("[notify] SMTP not configured, skip")
        return False
    try:
        msg = EmailMessage()
        msg["From"] = formataddr(("毛孩子记忆馆", SMTP_USER))
        msg["To"] = NOTIFY_TO
        msg["Subject"] = subject
        msg.set_content("请用支持 HTML 的客户端查看")
        msg.add_alternative(body_html, subtype="html")
        for fname, data, mime in (attachments or []):
            main, _, sub = (mime or "application/octet-stream").partition("/")
            msg.add_attachment(data, maintype=main or "application", subtype=sub or "octet-stream", filename=fname)
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=15) as s:
            s.login(SMTP_USER, SMTP_PASSWORD)
            s.send_message(msg)
        return True
    except Exception as e:
        print(f"[notify] send mail failed: {e}")
        return False


def notify_submission(sub, pet_photo_files=None):
    """sub: 提交字典；pet_photo_files: [(filename, bytes), ...]"""
    rows = [
        ("玩法", sub.get("play_type")),
        ("宠物", f"{sub.get('pet_name')}（{sub.get('pet_type')} / {sub.get('pet_status')} / {sub.get('pet_personality')}）"),
        ("主人昵称", sub.get("owner_name")),
        ("联系方式", sub.get("contact")),
        ("来源博主", sub.get("creator_source") or "—"),
        ("想要套餐", sub.get("want_package")),
        ("想说的话", sub.get("message")),
        ("是否同意样片", "是" if sub.get("allow_showcase") else "否"),
        ("提交时间", sub.get("created_at")),
        ("订单ID", sub.get("id")),
    ]
    body = "<h2>🐾 新提交</h2><table style='border-collapse:collapse'>"
    for k, v in rows:
        body += f"<tr><td style='padding:6px 12px;background:#fbefe2'><b>{k}</b></td><td style='padding:6px 12px'>{v or ''}</td></tr>"
    body += "</table>"
    attachments = []
    for fname, data in (pet_photo_files or []):
        ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else "jpg"
        mime = f"image/{ 'jpeg' if ext == 'jpg' else ext }"
        attachments.append((fname, data, mime))
    subject = f"【毛孩子记忆馆】新提交 · {sub.get('pet_name')} · {sub.get('contact')}"
    return send_mail(subject, body, attachments=attachments)


def notify_creator(c):
    rows = [
        ("昵称", c.get("nickname")),
        ("平台", c.get("platform")),
        ("粉丝数", c.get("followers")),
        ("主页", c.get("profile_url") or "—"),
        ("联系方式", c.get("contact")),
        ("是否愿意样片", "愿意" if c.get("wants_sample") else "先聊聊"),
        ("提交时间", c.get("created_at")),
    ]
    body = "<h2>🎀 新博主申请</h2><table style='border-collapse:collapse'>"
    for k, v in rows:
        body += f"<tr><td style='padding:6px 12px;background:#fbefe2'><b>{k}</b></td><td style='padding:6px 12px'>{v or ''}</td></tr>"
    body += "</table>"
    subject = f"【毛孩子记忆馆】新博主申请 · {c.get('nickname')} · {c.get('platform')}"
    return send_mail(subject, body)
