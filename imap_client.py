"""IMAP 拉取邮件：支持两种认证方式，按配置自动选择。

- 方式 A（默认）：QQ 邮箱等个人邮箱 —— 账号 + 授权码（config.imap_password），LOGIN 登录
- 方式 B：Microsoft 365 工作邮箱 —— OAuth2（MSAL 设备码），XOAUTH2 登录

从收件箱拉取最近 N 小时邮件并解析为结构化数据。
"""

import email
import email.message
import email.utils
import imaplib
import logging
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header

log = logging.getLogger(__name__)

# XOAUTH2 认证串：user=<邮箱>\x01auth=Bearer <token>\x01\x01
XOAUTH2_AUTH = "user={email}\x01auth=Bearer {token}\x01\x01"

# 按收件时间倒序排序时的空值兜底
_MIN_DT = datetime.min.replace(tzinfo=timezone.utc)


# ---- 连接（两种认证方式） ----

def connect(config: dict) -> imaplib.IMAP4_SSL:
    """建立 IMAP 连接并完成认证。"""
    server = config.get("imap_server", "outlook.office365.com")
    port = int(config.get("imap_port", 993))
    conn = imaplib.IMAP4_SSL(server, port)

    password = (config.get("imap_password") or "").strip()
    if password:
        # 方式 A：账号 + 授权码（QQ 邮箱等）
        conn.login(config["email"], password)
    else:
        # 方式 B：OAuth2（Microsoft 365 工作邮箱）
        import auth as auth_mod  # 延迟导入，密码模式不需要 MSAL

        token = auth_mod.IMAPTokenAuth(config).get_token()
        conn.authenticate(
            "XOAUTH2",
            lambda _: XOAUTH2_AUTH.format(email=config["email"], token=token).encode(),
        )
    return conn


# ---- 编码与正文解析 ----

def _decode_header(value: str | None) -> str:
    """解码 RFC2047 编码的主题/发件人（=?utf-8?B?...?=）。"""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def _simplify_from(raw: str) -> str:
    """把 '张三 <zhangsan@corp.com>' 简化为联系人名称 '张三'；
    无显示名时取邮箱前缀（如 newsletter@x.com → newsletter）。"""
    name, addr = email.utils.parseaddr(raw)
    name = name.strip().strip('"')
    if name:
        return name
    if addr:
        return addr.split("@", 1)[0]
    return raw


def _decode_payload(part: email.message.Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except (LookupError, TypeError):
        return payload.decode("utf-8", errors="replace")


def strip_html(html: str) -> str:
    """粗略地把 HTML 剥成可读文本（够摘要用即可）。"""
    text = re.sub(r"(?is)<style.*?</style>", " ", html)
    text = re.sub(r"(?is)<script.*?</script>", " ", text)
    text = re.sub(r"(?is)<br\s*/?>", "\n", text)
    text = re.sub(r"(?is)</(p|div|tr|li|h\d)>", "\n", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    for entity in ("&nbsp;", "&amp;", "&lt;", "&gt;", "&quot;"):
        text = text.replace(entity, " ")
    return re.sub(r"[ \t]+", " ", text).strip()


def _extract_text(msg: email.message.Message) -> str:
    """优先取 text/plain；无纯文本时从 text/html 剥标签。"""
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                text = _decode_payload(part)
                if text.strip():
                    return text
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return strip_html(_decode_payload(part))
        return ""
    ctype = msg.get_content_type()
    if ctype == "text/plain":
        return _decode_payload(msg)
    if ctype == "text/html":
        return strip_html(_decode_payload(msg))
    return ""


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = email.utils.parsedate_to_datetime(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _parse_message(msg: email.message.Message, max_body: int) -> dict:
    subject = _decode_header(msg.get("Subject", ""))
    body = _extract_text(msg) or subject
    return {
        "message_id": msg.get("Message-ID", "") or subject[:40],
        "from": _simplify_from(_decode_header(msg.get("From", ""))),
        "subject": subject,
        "received_at": _parse_date(msg.get("Date")),
        "body": body[:max_body],
    }


# ---- 拉取 ----

def fetch_recent_emails(config: dict, hours: int = 24) -> list[dict]:
    """返回收件箱最近 hours 小时内邮件的结构化列表（按收件时间倒序）。

    策略：不搜索全部邮件（大邮箱会极慢）。直接按投递顺序取最近 scan_recent
    封（默认 100）的邮件头 → 按 Date 过滤出窗口内的 → 仅对命中项取完整正文，
    最多 max_emails 封（默认 50）。适合"每日简报"这种只看最新邮件的场景。
    config: 配置 dict。返回元素含 from/subject/received_at(datetime)/body。
    """
    max_body = config.get("max_body_chars", 1000)
    max_emails = config.get("max_emails", 50)
    scan_recent = config.get("scan_recent", 100)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

    conn = connect(config)
    try:
        typ, data = conn.select("INBOX")
        if typ != "OK":
            raise RuntimeError("无法打开收件箱 INBOX")
        count = int(data[0])
        log.info("收件箱共 %d 封邮件", count)
        if count == 0:
            return []

        # 最近 scan_recent 封的序列号范围，一次命令取头部
        start = max(1, count - scan_recent + 1)
        typ, data = conn.fetch(
            f"{start}:{count}",
            "(BODY.PEEK[HEADER.FIELDS (DATE FROM SUBJECT MESSAGE-ID)])",
        )
        if typ != "OK":
            raise RuntimeError("IMAP 头部获取失败")

        headers = []
        for part in data:
            if isinstance(part, tuple) and len(part) == 2:
                seq = int(part[0].split(b" ", 1)[0])
                headers.append((seq, email.message_from_bytes(part[1])))
        log.info("已取最近 %d 封邮件头", len(headers))

        # 过滤出窗口内邮件，按时间倒序，最多 max_emails 封
        in_window = []
        for seq, msg in headers:
            dt = _parse_date(msg.get("Date"))
            if dt is not None and dt >= cutoff:
                in_window.append((seq, dt))
        log.info("窗口内 %d 封，最多处理 %d 封", len(in_window), max_emails)
        in_window.sort(key=lambda x: x[1], reverse=True)
        in_window = in_window[:max_emails]

        # 仅对命中项取完整正文
        emails = []
        for seq, _ in in_window:
            typ, data = conn.fetch(str(seq), "(RFC822)")
            if typ != "OK" or not data or data[0] is None:
                continue
            item = _parse_message(email.message_from_bytes(data[0][1]), max_body)
            emails.append(item)

        emails.sort(key=lambda e: e["received_at"] or _MIN_DT, reverse=True)
        return emails
    finally:
        try:
            conn.logout()
        except Exception:
            pass
