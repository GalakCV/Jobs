"""Notificações de vagas NOVAS: Discord (webhook), Telegram (bot) e Notion (banco).

Credenciais vêm de variáveis de ambiente (arquivo .env). Cada notificador é
independente: se um falhar, os outros continuam. Uma vaga só é marcada como
notificada se TODOS os canais habilitados aceitaram o envio.
"""

from __future__ import annotations

import html
import logging
import os
import time
from abc import ABC, abstractmethod

import requests

from jobcrawler.exporters import AREA_LABELS

log = logging.getLogger(__name__)
TIMEOUT = 20


def _post_with_retry(url: str, *, json_body: dict, headers: dict | None = None,
                     attempts: int = 3) -> requests.Response:
    """POST com retry simples para 429/5xx (Discord e Telegram informam o tempo de espera)."""
    resp: requests.Response | None = None
    for attempt in range(attempts):
        resp = requests.post(url, json=json_body, headers=headers, timeout=TIMEOUT)
        if resp.status_code == 429 or resp.status_code >= 500:
            wait = 2.0 * (attempt + 1)
            try:
                body = resp.json()
                wait = float(body.get("retry_after")
                             or body.get("parameters", {}).get("retry_after") or wait)
            except ValueError:
                pass
            log.warning("Notificação recebeu HTTP %d, aguardando %.1fs", resp.status_code, wait)
            time.sleep(min(wait, 60))
            continue
        return resp
    assert resp is not None
    return resp


def _line(job: dict) -> str:
    parts = [job.get("company") or "", job.get("location") or job.get("regions") or ""]
    if job.get("timezone"):
        parts.append(f"fuso: {job['timezone']}")
    return " · ".join(p for p in parts if p)


class Notifier(ABC):
    name = "base"

    @abstractmethod
    def send(self, jobs: list[dict]) -> bool:
        """Envia as vagas. Retorna True se todas foram aceitas pelo canal."""


class DiscordNotifier(Notifier):
    name = "discord"

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    def send(self, jobs: list[dict]) -> bool:
        ok = True
        for i in range(0, len(jobs), 10):  # Discord aceita até 10 embeds por mensagem
            embeds = [{
                "title": job["title"][:256],
                "url": job["url"],
                "description": _line(job)[:4000],
                "fields": [
                    {"name": "Área", "value": AREA_LABELS.get(job.get("area"), job.get("area") or "-"),
                     "inline": True},
                    {"name": "Fonte", "value": job.get("source") or "-", "inline": True},
                ],
                "timestamp": job.get("published_at") or None,
            } for job in jobs[i:i + 10]]
            resp = _post_with_retry(self.webhook_url, json_body={
                "content": "🆕 Novas vagas remotas júnior" if i == 0 else None,
                "embeds": embeds,
            })
            if resp.status_code not in (200, 204):
                log.error("Discord recusou (HTTP %d): %s", resp.status_code, resp.text[:200])
                ok = False
        return ok


class TelegramNotifier(Notifier):
    name = "telegram"

    def __init__(self, token: str, chat_id: str):
        self.url = f"https://api.telegram.org/bot{token}/sendMessage"
        self.chat_id = chat_id

    def send(self, jobs: list[dict]) -> bool:
        ok = True
        for i in range(0, len(jobs), 5):  # 5 vagas por mensagem fica abaixo do limite de 4096
            blocks = []
            for job in jobs[i:i + 5]:
                area = AREA_LABELS.get(job.get("area"), job.get("area") or "")
                blocks.append(
                    f"<b><a href=\"{html.escape(job['url'], quote=True)}\">"
                    f"{html.escape(job['title'])}</a></b>\n"
                    f"{html.escape(_line(job))}\n<i>{html.escape(area)} · {html.escape(job.get('source') or '')}</i>")
            resp = _post_with_retry(self.url, json_body={
                "chat_id": self.chat_id,
                "text": "\n\n".join(blocks)[:4096],
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            })
            if resp.status_code != 200:
                log.error("Telegram recusou (HTTP %d): %s", resp.status_code, resp.text[:200])
                ok = False
        return ok


class NotionNotifier(Notifier):
    """Cria uma página por vaga em um banco do Notion.

    O banco precisa ter estas propriedades (nomes exatos):
      Name (Título) · Company (Texto) · Area (Seleção) · Location (Texto)
      Source (Seleção) · URL (URL) · Published (Data)
    """
    name = "notion"
    API = "https://api.notion.com/v1/pages"

    def __init__(self, token: str, database_id: str):
        self.database_id = database_id.replace("-", "")
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _text(value: str) -> list[dict]:
        return [{"text": {"content": (value or "")[:1900]}}]

    def send(self, jobs: list[dict]) -> bool:
        ok = True
        for job in jobs:
            props = {
                "Name": {"title": self._text(job["title"])},
                "Company": {"rich_text": self._text(job.get("company", ""))},
                "Area": {"select": {"name": AREA_LABELS.get(job.get("area"), job.get("area") or "Outro")}},
                "Location": {"rich_text": self._text(job.get("location") or job.get("regions") or "")},
                "Source": {"select": {"name": job.get("source") or "desconhecida"}},
                "URL": {"url": job["url"]},
            }
            if job.get("published_at"):
                props["Published"] = {"date": {"start": job["published_at"]}}
            resp = _post_with_retry(self.API, headers=self.headers, json_body={
                "parent": {"database_id": self.database_id}, "properties": props})
            if resp.status_code != 200:
                log.error("Notion recusou '%s' (HTTP %d): %s",
                          job["title"], resp.status_code, resp.text[:300])
                ok = False
            time.sleep(0.4)  # limite médio do Notion: ~3 requisições/s
        return ok


def build_notifiers(cfg: dict) -> list[Notifier]:
    """Instancia os notificadores habilitados no config que têm credenciais no .env."""
    notifiers: list[Notifier] = []
    if cfg.get("discord"):
        if url := os.getenv("DISCORD_WEBHOOK_URL"):
            notifiers.append(DiscordNotifier(url))
        else:
            log.warning("Discord habilitado, mas DISCORD_WEBHOOK_URL não está definido")
    if cfg.get("telegram"):
        token, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
        if token and chat:
            notifiers.append(TelegramNotifier(token, chat))
        else:
            log.warning("Telegram habilitado, mas TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID faltando")
    if cfg.get("notion"):
        token, db = os.getenv("NOTION_TOKEN"), os.getenv("NOTION_DATABASE_ID")
        if token and db:
            notifiers.append(NotionNotifier(token, db))
        else:
            log.warning("Notion habilitado, mas NOTION_TOKEN/NOTION_DATABASE_ID faltando")
    return notifiers
