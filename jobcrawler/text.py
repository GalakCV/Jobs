"""Utilitários de normalização de texto, datas e identificadores."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from bs4 import BeautifulSoup

_WS = re.compile(r"\s+")


def clean_ws(value: str | None) -> str:
    """Colapsa espaços/quebras de linha e remove bordas."""
    return _WS.sub(" ", value or "").strip()


def fix_mojibake(value: str) -> str:
    """Corrige texto UTF-8 que foi decodificado como Latin-1 (ex.: 'â€™').

    Algumas APIs (RemoteOK, por exemplo) às vezes entregam texto assim. Se a
    correção falhar, devolve o texto original sem alterar nada.
    """
    if not value or not any(marker in value for marker in ("Ã", "â€", "Â")):
        return value
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def html_to_text(value: str | None) -> str:
    """Converte HTML de descrição de vaga em texto plano legível."""
    if not value:
        return ""
    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    return clean_ws(fix_mojibake(soup.get_text(" ")))


def fold(value: str | None) -> str:
    """Minúsculo + sem acentos: 'Sênior Estágio' -> 'senior estagio'.

    Todo o motor de filtros compara contra texto "dobrado" assim, para que os
    termos em português funcionem com ou sem acento.
    """
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_marks = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return clean_ws(without_marks.lower())


def parse_date(value: Any) -> str | None:
    """Normaliza datas das fontes para ISO-8601 em UTC.

    Aceita: epoch em segundos ou milissegundos, ISO-8601 (com ou sem fuso) e
    RFC-2822 (usado em RSS). Retorna None se não conseguir interpretar.
    """
    if value in (None, ""):
        return None
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
            ts = float(value)
            if ts > 1e12:  # milissegundos
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(timespec="seconds")
        text = str(value).strip()
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat(timespec="seconds")
    except (ValueError, TypeError, OverflowError, IndexError):
        return None


def age_in_days(iso_date: str | None, now: datetime | None = None) -> float | None:
    """Quantos dias se passaram desde a data ISO (None se desconhecida)."""
    if not iso_date:
        return None
    try:
        dt = datetime.fromisoformat(iso_date)
    except ValueError:
        return None
    now = now or datetime.now(timezone.utc)
    return (now - dt).total_seconds() / 86400


def fingerprint(title: str, company: str) -> str:
    """Chave de deduplicação entre fontes: mesma vaga em WWR e Remotive = 1 registro."""
    key = f"{fold(title)}|{fold(company)}"
    key = re.sub(r"[^a-z0-9|]+", "", key)
    return hashlib.sha1(key.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Fuso horário exigido
# ---------------------------------------------------------------------------
_TZ_ABBREV = re.compile(
    r"(?<![A-Za-z])(EST|EDT|CST|CDT|MST|MDT|PST|PDT|AEST|AEDT|ACST|AWST|"
    r"(?:UTC|GMT)\s?[+\-−]\s?\d{1,2}(?::?\d{2})?)(?![A-Za-z])"
)
_TZ_NAMES = re.compile(
    r"\b(eastern|central|mountain|pacific|atlantic|australian eastern|"
    r"australian western|australian central)\s+(?:standard\s+|daylight\s+)?time\b",
    re.IGNORECASE,
)
_TZ_SHORT = re.compile(r"(?<![A-Za-z])(ET|CT|MT|PT)(?=\s*(?:hours|time zone|timezone|\)|,|/|$))")


def extract_timezones(*texts: str) -> str:
    """Encontra menções a fusos horários exigidos (ex.: 'EST', 'UTC-5', 'Pacific Time')."""
    found: list[str] = []
    for text in texts:
        if not text:
            continue
        for match in _TZ_ABBREV.findall(text):
            found.append(re.sub(r"\s+", "", match.replace("−", "-")).upper())
        for match in _TZ_NAMES.findall(text):
            found.append(f"{match.title()} Time")
        for match in _TZ_SHORT.findall(text):
            found.append(match)
    # remove duplicatas preservando ordem
    return ", ".join(dict.fromkeys(found))


def utc_offsets_to_label(offsets: list[float] | None) -> str:
    """Converte lista de offsets UTC (formato Himalayas) em rótulo curto."""
    if not offsets:
        return ""
    values = sorted(set(float(x) for x in offsets))
    if len(values) >= 24:  # praticamente todos os fusos
        return "Qualquer fuso"

    def fmt(x: float) -> str:
        sign = "+" if x >= 0 else "-"
        hours = int(abs(x))
        minutes = int(round((abs(x) - hours) * 60))
        return f"UTC{sign}{hours}" + (f":{minutes:02d}" if minutes else "")

    # Agrupa offsets contíguos (diferença <= 1h) para mostrar faixas legíveis.
    # Ex.: [-10..-5, 14] -> "UTC-10 a UTC-5, UTC+14" (o +14 é o Himalayas
    # incluindo ilhas dos EUA no Pacífico).
    groups: list[list[float]] = [[values[0]]]
    for v in values[1:]:
        if v - groups[-1][-1] <= 1:
            groups[-1].append(v)
        else:
            groups.append([v])
    parts = [fmt(g[0]) if len(g) == 1 else f"{fmt(g[0])} a {fmt(g[-1])}" for g in groups]
    return ", ".join(parts)
