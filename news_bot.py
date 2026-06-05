#!/usr/bin/env python3
"""
Telegram AI/Tech News Bot
"""

import json
import os
import time
import hashlib
import logging
import re
from datetime import datetime
from pathlib import Path

import feedparser
import requests
import anthropic

BASE_DIR = Path(__file__).parent
CONFIG_FILE = BASE_DIR / "config.json"
HISTORY_FILE = BASE_DIR / "posted_history.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler()])
log = logging.getLogger(__name__)

DEFAULT_FEEDS = [
    {"url": "https://techcrunch.com/feed/", "name": "TechCrunch"},
    {"url": "https://www.theverge.com/rss/index.xml", "name": "The Verge"},
    {"url": "https://feeds.arstechnica.com/arstechnica/index", "name": "Ars Technica"},
    {"url": "https://venturebeat.com/category/ai/feed/", "name": "VentureBeat AI"},
    {"url": "https://www.wired.com/feed/rss", "name": "Wired"},
    {"url": "https://artificialintelligence-news.com/feed/", "name": "AI News"},
    {"url": "https://www.technologyreview.com/feed/", "name": "MIT Tech Review"},
    {"url": "https://openai.com/news/rss.xml", "name": "OpenAI Blog"},
    {"url": "https://deepmind.google/blog/rss.xml", "name": "Google DeepMind"},
    {"url": "https://huggingface.co/blog/feed.xml", "name": "HuggingFace Blog"},
]

SYSTEM_PROMPT = """Ты редактор Telegram-канала о технологиях и искусственном интеллекте.
Твоя задача — превратить новость в короткий, цепляющий пост для русскоязычной аудитории.

Правила:
- Длина поста: 3-5 предложений (не более 800 символов)
- Язык: живой, понятный русский, без канцелярита
- Начни с самого важного
- Используй 1-2 эмодзи для визуального акцента
- В конце добавь 3-5 хэштегов
- НЕ добавляй ссылку — она будет добавлена автоматически
"""

def load_config():
    with open(CONFIG_FILE, encoding="utf-8") as f:
        return json.load(f)

def load_history():
    if HISTORY_FILE.exists():
        with open(HISTORY_FILE, encoding="utf-8") as f:
            return set(json.load(f).get("posted", []))
    return set()

def save_history(history):
    trimmed = list(history)[-5000:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump({"posted": trimmed, "updated": datetime.now().isoformat()}, f, ensure_ascii=False)

def item_id(entry):
    key = entry.get("id") or entry.get("link") or entry.get("title", "")
    return hashlib.md5(key.encode()).hexdigest()

def fetch_news(feeds, history, max_per_feed=5):
    fresh = []
    for feed_cfg in feeds:
        url = feed_cfg["url"]
        source = feed_cfg.get("name", url)
        try:
            parsed = feedparser.parse(url)
            for entry in parsed.entries[:max_per_feed]:
                eid = item_id(entry)
                if eid in history:
                    continue
                title = entry.get("title", "").strip()
                link = entry.get("link", "").strip()
                summary = re.sub(r"<[^>]+>", "", entry.get("summary", entry.get("description", "")).strip())[:800]
                if title and link:
                    fresh.append({"id": eid, "title": title, "link": link, "summary": summary, "source": source})
            log.info(f"OK {source}")
        except Exception as e:
            log.warning(f"RSS error {source}: {e}")
    return fresh

def generate_post(item, client):
    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": f"Источник: {item['source']}\nЗаголовок: {item['title']}\nОписание: {item['summary']}\n\nНапиши пост для Telegram."}]
        )
        return msg.content[0].text.strip() + f"\n\n🔗 [Читать полностью]({item['link']})"
    except Exception as e:
        log.error(f"Claude error: {e}")
        return None

def post_to_telegram(text, bot_token, channel_id):
    try:
        r = requests.post(f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": channel_id, "text": text, "parse_mode": "Markdown"}, timeout=15)
        if r.status_code == 200:
            log.info("Posted!")
            return True
        log.error(f"Telegram error {r.status_code}: {r.text}")
        return False
    except Exception as e:
        log.error(f"Send error: {e}")
        return False

def run():
    log.info("Bot starting...")
    config = load_config()
    client = anthropic.Anthropic(api_key=config["anthropic_api_key"])
    history = load_history()
    feeds = config.get("feeds", DEFAULT_FEEDS)
    fresh = fetch_news(feeds, history)
    log.info(f"Found {len(fresh)} new items")
    if not fresh:
        return
    published = 0
    for item in fresh[:config.get("max_posts_per_run", 3)]:
        post = generate_post(item, client)
        if post and post_to_telegram(post, config["bot_token"], config["channel_id"]):
            history.add(item["id"])
            published += 1
            if published < config.get("max_posts_per_run", 3):
                time.sleep(config.get("delay_between_posts_seconds", 15))
    save_history(history)
    log.info(f"Done. Published: {published}")

if __name__ == "__main__":
    run()
