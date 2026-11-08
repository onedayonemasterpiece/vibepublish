"""Read canonical carousel guidance in short, source-faithful steps and sections."""
from __future__ import annotations

import re
import sysconfig
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from .carousel_compositor import render_document_svg
from .domain import DomainError

_DOC_DIR = Path(__file__).resolve().parents[1] / "docs" / "llm" / "carousel"
_INSTALL_DIR = Path(sysconfig.get_path("data")) / "share" / "vibepublish" / "carousel"
_SOURCE = "docs/llm/carousel/"


@dataclass(frozen=True, slots=True)
class GuideImages:
    metadata: dict
    images: tuple[bytes, ...]


def _read(name: str) -> str:
    root = _DOC_DIR if _DOC_DIR.is_dir() else _INSTALL_DIR
    return (root / name).read_text(encoding="utf-8")


def _sections(source: str) -> list[tuple[str, str]]:
    """The introductory material and diagrams before the first ## are Введение."""
    headings = list(re.finditer(r"(?m)^##[ \t]+(.+?)[ \t]*$", source))
    result = []
    first = headings[0].start() if headings else len(source)
    if source[:first].strip():
        result.append(("Введение", source[:first].strip()))
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(source)
        result.append((heading.group(1).strip(), source[heading.start():end].strip()))
    return result


def guide(topic: str | None = None, section: str | None = None) -> dict | GuideImages:
    """README and step cards fit in one response; chapters require an explicit section."""
    index = _read("README.md")
    topics = re.findall(r"(?m)^\|\s*\[([0-9]{2}-[a-z-]+)\]\(\1\.md\)\s*\|", index)
    step_line = re.search(r"(?m)^Шаги:\s*(.+)$", index)
    if step_line:
        topics = ["steps/" + step for step in re.findall(
            r"\bs(?:0[1-9]|10)\b", step_line.group(1))] + topics
    if topic is None:
        return {"private": True, "topics": topics, "content": index,
                "sources": [_SOURCE + "README.md"]}
    if topic not in topics:
        raise DomainError("invalid_input", f"Unknown Story Carousel guide topic: {topic}")

    source = _read(topic + ".md")
    sources = [_SOURCE + topic + ".md"]
    metadata = {"private": True, "topic": topic, "sources": sources}
    question = (_review_bank().get(section.strip().upper())
                if topic == "90-review" and section else None)
    if question:
        metadata["section"] = question["id"]
        if question["id"].startswith("ST"):
            sources[:] = [_SOURCE + "85-style-continuity.md"]
        content = (f"# {question['id']}. {question['question']}\n\n"
                   f"Что наблюдать: {question['observe']}\n\n"
                   f"Возможная правка: {question['suggestion']}")
    elif topic.startswith("steps/"):
        if section:
            raise DomainError("invalid_input", "Step cards do not contain named sections")
        content = source
    else:
        headings = _sections(source)
        if section is None:
            lines = [f"# {topic} — разделы", "", "Выбери один раздел параметром section.",
                     "", "| Раздел | Знаков |", "|---|---:|"]
            lines += [f"| {title} | {len(text)} |" for title, text in headings]
            if topic == "90-review":
                lines += ["", 'Один вопрос: section:"Q01"; также доступны ID V, R, K и ST. '
                          'Выбирай нужный вопрос, весь банк читать не требуется.']
            content = "\n".join(lines)
        else:
            query = section.strip().casefold()
            exact = [(title, text) for title, text in headings if title.casefold() == query]
            found = exact or [(title, text) for title, text in headings
                              if title.casefold().startswith(query)]
            if len(found) != 1:
                raise DomainError("invalid_input", f"Guide section must match one heading of {topic}: {section}")
            metadata["section"] = found[0][0]
            content = found[0][1]

    metadata["content"] = content
    images = []
    image_meta = []
    for name in dict.fromkeys(re.findall(r"!\[[^\]]*\]\((img/[A-Za-z0-9._-]+\.svg)\)", content)):
        svg = _read(name)
        root = ET.fromstring(svg)
        width, height = int(root.attrib["width"]), int(root.attrib["height"])
        images.append(render_document_svg(svg, width=width, height=height))
        image_meta.append({"path": _SOURCE + name, "mime_type": "image/png",
                           "width": width, "height": height})
        sources.append(_SOURCE + name)
    if images:
        metadata["images"] = image_meta
        return GuideImages(metadata, tuple(images))
    return metadata


def _review_bank() -> dict[str, dict]:
    """One source-table parser for render hints and individual guide questions."""
    source = _read("90-review.md")
    bank = {}
    for row in (source + "\n" + _read("85-style-continuity.md")).splitlines():
        if not row.startswith("|"):
            continue
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        if len(cells) == 3:
            match = re.fullmatch(r"([QVR]\d{2})\.\s+(.+)", cells[0])
            if match:
                bank[match[1]] = {"id": match[1], "question": match[2],
                                  "observe": cells[1], "suggestion": cells[2]}
        elif len(cells) == 4 and re.fullmatch(r"(?:[QVRK]\d{2}|ST[1-7])", cells[0]):
            bank[cells[0]] = {"id": cells[0], "question": cells[1],
                              "observe": cells[2], "suggestion": cells[3]}
    return bank


def review_questions(view: str) -> list[dict]:
    """Respect the guide author's priorities; other questions remain addressable by ID."""
    source = _read("90-review.md")
    line = re.search(r"(?m)^- \[" + re.escape(view) + r"\]\s+(.+)$", source)
    if not line:
        raise DomainError("invalid_input", f"Story Carousel review tag missing: {view}")
    ids = re.findall(r"\b(?:[QVRK]\d{2}|ST[1-7])\b", line.group(1))
    bank = _review_bank()
    return [bank[ident] for ident in ids[:5]]
