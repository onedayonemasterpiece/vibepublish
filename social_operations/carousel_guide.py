"""Read canonical carousel guidance in short, source-faithful steps and sections."""
from __future__ import annotations

import re
import json
import hashlib
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
    question_id = section.strip().upper() if topic == "90-review" and section else ""
    question = _review_bank().get(question_id.removeprefix("QUESTION:")) if question_id else None
    # Keep existing heading prefixes (notably K01 and R01) unambiguous.
    if question and not question_id.startswith("QUESTION:"):
        if any(title.upper().startswith(question_id) for title, _ in _sections(source)):
            question = None
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
                lines += ["", 'Один вопрос: section:"question:Q01"; также доступны ID V, R, K и ST. '
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


def guide_digest():
    root = _DOC_DIR if _DOC_DIR.is_dir() else _INSTALL_DIR
    files = sorted(path for path in root.rglob('*') if path.suffix in {'.md', '.svg'})
    return hashlib.sha256(json.dumps({str(path.relative_to(root)): path.read_text(encoding='utf-8')
        for path in files}, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def work_context(row, action, guide_sha=None):
    """Recorded facts and one advisory address, never a semantic or visual gate."""
    story = row.get('story')
    if 'story' not in row:
        story = json.loads(row['story_json']) if row['story_json'] else None
    facts = [{'basis': 'observed', 'status': 'recorded', 'text':
        f"{action}: ревизия {row['revision']}; " + (f"сохранено материалов: {len(story['materials'])}."
        if story is not None else 'legacy brief сохранён; structured материалы не зарегистрированы.')}]
    unlinked = [] if story is None else [point for point in story['points']
        if not any(point['id'] in card['point_ids'] for card in story['cards'])]
    declared = 'Связи point→card не зарегистрированы; понимание неизвестно.'
    if story is not None:
        declared = (f"Нет заявленной привязки {unlinked[0]['id']}; фрагмент пункта: {unlinked[0]['text'][:160]}"
                    if unlinked else f"Зарегистрировано пунктов: {len(story['points'])}; без заявленной привязки: 0. Понимание не проверено.")
    facts += [{'basis': 'model_declared', 'status': 'recorded' if story is not None else 'not_registered',
               'text': declared}, {'basis': 'reviewed', 'status': 'not_registered',
               'text': 'Независимое понимание читателем в этом контракте не зарегистрировано; качество unknown.'}]
    if story is None or not story['materials'] or not story['points'] or not story['narrative'].strip():
        focus, topic, text = 'source_material', 'steps/s01', 'Уточни сохранённые источники, смысловые пункты и цельный рассказ; первичку не сокращай.'
    elif unlinked:
        focus, topic, text = 'declared_coverage', 'steps/s02', f"Проверь, как карточки раскрывают пункт {unlinked[0]['id']}; связь сама по себе не доказывает понимание."
    elif action == 'export':
        focus, topic, text = 'publication', '99-platform', 'Перед порученной публикацией проверь точный экспорт и параметры назначения.'
    else:
        focus, topic, text = ('visual_review', 'steps/s09', 'Прочитай реальные изображения этой ревизии, отдельно карточки и всю историю.') if row['svg'] else (
            'composition', 'steps/s03', 'Сопоставь разные генеративные эскизы общей композиции с историей.')
    address = {'kind': 'get', 'scope': 'guide', 'carousel_id': row['id'], 'topic': topic}
    if topic == '99-platform':
        address['section'] = 'Перед публикацией'
    return {'revision': row['revision'], 'guide_sha256': guide_sha or guide_digest(), 'facts': facts,
            'recommendation': {'suggested_focus': focus, 'text': text, 'get': address}}


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


def review_questions(view: str, *, source_svg: str | None = None) -> list[dict]:
    """Respect the guide author's priorities; other questions remain addressable by ID."""
    source = _read("90-review.md")
    line = re.search(r"(?m)^- \[" + re.escape(view) + r"\]\s+(.+)$", source)
    if not line:
        raise DomainError("invalid_input", f"Story Carousel review tag missing: {view}")
    ids = re.findall(r"\b(?:[QVRK]\d{2}|ST[1-7])\b", line.group(1))
    bank = _review_bank()
    questions = [bank[ident] for ident in ids]
    target = next((q for q in questions if q["id"] == "K19"), questions[0] if questions else None)
    if source_svg is not None and target is not None:
        text_nodes = sum(node.tag in ("text", "{http://www.w3.org/2000/svg}text")
                         for node in ET.fromstring(source_svg).iter())
        target["observe"] += (
            f" Факт исходного SVG: {text_nodes} узлов <text> (scope=document, включая defs/скрытые)."
            " Это не число видимых или крупных надписей выбранной карточки; tspan, копии use,"
            " растры и контуры не считаются, происхождение растров не определяется.")
    return questions
