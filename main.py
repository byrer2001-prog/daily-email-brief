"""每日邮件简报入口：读取收件箱最近 N 小时邮件 → 本地 Ollama 摘要 → 输出 JSON。

用法：
  python main.py --test-auth   # 仅验证 IMAP 授权与连通
  python main.py --list        # 只列出邮件，不调摘要
  python main.py [--hours 48]  # 正常生成简报（默认 24 小时）

认证方式由 config.json 自动决定：
  - 填了 imap_password → 账号+授权码（QQ 邮箱等，LOGIN）
  - 未填 imap_password   → OAuth2 设备码（Microsoft 365，XOAUTH2）
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import imap_client
import summarize as summarize_mod

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("brief")

PROJECT_DIR = Path(__file__).parent


def load_config() -> dict:
    with open(PROJECT_DIR / "config.json", encoding="utf-8") as f:
        return json.load(f)


def check_email_configured(cfg: dict) -> bool:
    email = cfg.get("email") or ""
    if not email or email.startswith("你的"):
        log.error("请先在 config.json 中填写你的邮箱（email 字段）")
        return False

    # QQ 邮箱必须填授权码，否则会误走 OAuth2 流程
    password = (cfg.get("imap_password") or "").strip()
    if not password and "qq.com" in cfg.get("imap_server", ""):
        log.error(
            "QQ 邮箱需要授权码：请在网页版 mail.qq.com → 设置 → 账号 → 开启 IMAP/SMTP 服务，"
            "获取授权码后填入 config.json 的 imap_password 字段"
        )
        return False
    return True


def test_auth(cfg: dict) -> int:
    """验证 IMAP 连通与认证，不拉取正文。"""
    try:
        conn = imap_client.connect(cfg)
    except Exception as e:  # noqa: BLE001 - 统一转成对用户友好的提示
        log.error("邮箱连接失败：%s", e)
        print("提示：QQ 邮箱请确认已在 mail.qq.com 开启 IMAP 并填好授权码（config.json 的 imap_password）")
        return 1
    try:
        typ, _ = conn.select("INBOX")
        if typ == "OK":
            print(f"✅ 授权成功并已连接邮箱：{cfg['email']}")
            return 0
        print("⚠️ 授权成功，但无法打开收件箱 INBOX")
        return 1
    finally:
        try:
            conn.logout()
        except Exception:
            pass


def build_report(emails: list[dict], cfg: dict, hours: int) -> dict:
    now = datetime.now().astimezone()
    return {
        "generated_at": now.isoformat(),
        "period": {
            "start": (now - timedelta(hours=hours)).isoformat(),
            "end": now.isoformat(),
        },
        "total": len(emails),
        "emails": [
            {
                "from": e["from"],
                "subject": e["subject"],
                "received_at": e["received_at"].isoformat()
                if e["received_at"]
                else None,
                "summary": e["summary"],
            }
            for e in emails
        ],
    }


def save_report(report: dict, cfg: dict) -> Path:
    out_dir = PROJECT_DIR / cfg.get("output_dir", "briefs")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"daily_brief_{datetime.now().strftime('%Y-%m-%d')}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    return out_file


def print_report(report: dict) -> None:
    print(f"\n===== 今日邮件简报（{report['period']['end'][:10]}） =====")
    for e in report["emails"]:
        print(f"· {e['from']} | {e['subject']}")
        print(f"   {e['summary']}")
    print("=========================")


def main() -> int:
    parser = argparse.ArgumentParser(description="每日邮件简报")
    parser.add_argument("--test-auth", action="store_true", help="仅验证授权与连通")
    parser.add_argument("--list", action="store_true", help="只列出邮件，不生成摘要")
    parser.add_argument("--hours", type=int, default=None, help="覆盖邮件窗口小时数")
    args = parser.parse_args()

    cfg = load_config()
    if not check_email_configured(cfg):
        return 2

    hours = args.hours or cfg.get("hours", 24)

    if args.test_auth:
        return test_auth(cfg)

    log.info("正在读取 %s 最近 %d 小时的邮件...", cfg["email"], hours)
    emails = imap_client.fetch_recent_emails(cfg, hours=hours)
    log.info("共 %d 封邮件", len(emails))

    if args.list:
        for e in emails:
            t = e["received_at"].strftime("%m-%d %H:%M") if e["received_at"] else "??"
            print(f"[{t}] {e['from']} | {e['subject']}")
        return 0

    summarizer = summarize_mod.Summarizer(cfg)
    for e in emails:
        log.info("生成摘要：%s | %s", e["from"], e["subject"])
        e["summary"] = summarizer.summarize(e)
        e.pop("body", None)  # 简报不包含正文

    report = build_report(emails, cfg, hours)
    out_file = save_report(report, cfg)
    log.info("简报已写入 %s", out_file)
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
