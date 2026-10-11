"""We Work Remotely - feeds RSS públicos (https://weworkremotely.com/remote-job-rss-feed).

O título do item vem como "Empresa: Cargo". A restrição geográfica real fica
em <country>/<state>; <region> costuma ser genérico ("Anywhere in the World").
O XML é lido com defusedxml (proteção contra XML malicioso).
"""

from __future__ import annotations

import re
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

from jobcrawler.models import Job
from jobcrawler.sources.base import SchemaChangedError, Source, SourceResult, parse_many
from jobcrawler.text import clean_ws, html_to_text, parse_date

_FLAGS = re.compile(r"[\U0001F1E6-\U0001F1FF]")  # emojis de bandeira em <country>


def _text(item: Element, tag: str) -> str:
    node = item.find(tag)
    return clean_ws(node.text) if node is not None and node.text else ""


def location_from_item(item: Element) -> str:
    country = clean_ws(_FLAGS.sub("", _text(item, "country"))).replace(" and ", ", ")
    state = _text(item, "state")
    region = _text(item, "region")
    if country:                       # restrição explícita por país tem prioridade
        return ", ".join(p for p in (country, state) if p)
    if state:                         # estado sem país => estado dos EUA
        return f"{state}, United States"
    return region


def parse_item(item: Element) -> Job:
    raw_title = _text(item, "title")
    company, _, title = raw_title.partition(": ")
    if not title:                     # formato inesperado: mantém o título inteiro
        company, title = "", raw_title
    link = _text(item, "link") or _text(item, "guid")
    return Job(
        source="weworkremotely",
        title=title,
        company=company,
        url=link,
        location=location_from_item(item),
        description=html_to_text(_text(item, "description")),
        published_at=parse_date(_text(item, "pubDate")),
        tags=[t.strip() for t in _text(item, "skills").split(",") if t.strip()][:8],
        source_category=_text(item, "category"),
    )


def parse_feed(xml_text: str) -> list[Element]:
    try:
        root = SafeET.fromstring(xml_text.encode("utf-8"))
    except SafeET.ParseError as exc:
        raise SchemaChangedError(f"RSS inválido: {exc}") from exc
    channel = root.find("channel")
    if channel is None:
        raise SchemaChangedError("RSS sem <channel>")
    return channel.findall("item")


class WeWorkRemotelySource(Source):
    name = "weworkremotely"

    def fetch(self) -> SourceResult:
        result = SourceResult(self.name)
        for feed in self.cfg.get("feeds", []):
            def run(url=feed):
                return parse_many(parse_feed(self.http.get_text(url)), parse_item, self.name)
            self._safe(result, feed.rsplit("/", 1)[-1], run)
        return result
