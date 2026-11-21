"""Jednorazowa ekstrakcja bazy wiedzy z `context/` do `docs/assistant/wiedza/*.md`.

Uruchomienie (wymaga `pip install pypdf`; aplikacja tego pakietu nie potrzebuje):
    python -m app.assistant.hr.knowledge_build

`context/` zostaje nietknięty. Wynik to Markdown: `## <etykieta jednostki>` + tekst,
czytany przez `knowledge.py`. Standardy ZZL pomijamy — PDF ma uszkodzone kodowanie fontów.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path

from app.settings import ROOT

CONTEXT = ROOT / "context"
OUT = ROOT / "docs" / "assistant" / "wiedza"

ROZP = CONTEXT / "1. Akty prawne" / "1. Rozporządzenie w sprawie ocen okresowych.pdf"
USTAWA = CONTEXT / "1. Akty prawne" / "2. Ustawa o służbie cywilnej - wyciąg przepisów.docx"
PORADNIK = CONTEXT / "6. Materiały dodatkowe" / "Poradnik - oceny okresowe w służbie cywilnej.pdf"


def _pdf_pages(path: Path) -> list[str]:
    import pypdf

    return [(p.extract_text() or "") for p in pypdf.PdfReader(str(path)).pages]


def _docx_paragraphs(path: Path) -> list[str]:
    xml = zipfile.ZipFile(path).read("word/document.xml").decode("utf-8")
    paras = re.split(r"</w:p>", xml)
    texts = (re.sub(r"<[^>]+>", "", p).replace("\xa0", " ").strip() for p in paras)
    return [t for t in texts if t]


def _clean(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"-\n(?=[a-ząćęłńóśźż])", "", text)  # dzielenie wyrazów
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    # łączymy łamane wiersze, zostawiamy nowe akapity przed punktami/ustępami
    text = re.sub(r"\n(?!(\d+[.)]|[a-z]\)|§|Art\.|–|-|•|\d+\.\d+))", " ", text)
    text = re.sub(r"[ ]{2,}", " ", text)
    return text.strip()


def build_rozporzadzenie() -> str:
    pages = _pdf_pages(ROZP)
    text = "\n".join(pages)
    text = re.sub(r"Dziennik Ustaw\s*–\s*\d+\s*–\s*Poz\. 470\s*", "", text, flags=re.IGNORECASE)
    end = text.find("Załącznik nr 2")
    text = text[:end] if end > 0 else text
    start = text.find("§ 1.")
    body, annex_at = text[start:], text.find("Załącznik nr 1", start)
    if annex_at > 0:
        body = text[start:annex_at]
    units = re.split(r"\n(?=§ \d+\.)", body)
    out = ["# Rozporządzenie PRM z 4.04.2016 w sprawie ocen okresowych (Dz. U. poz. 470)\n"]
    for unit in units:
        m = re.match(r"§ (\d+)\.", unit.strip())
        if not m:
            continue
        out.append(f"## § {m.group(1)} rozporządzenia\n\n{_clean(unit)}\n")
    if annex_at > 0:
        out.append(f"## Załącznik nr 1 do rozporządzenia (wykaz kryteriów)\n\n{_clean(text[annex_at:])}\n")
    return "\n".join(out)


def build_ustawa() -> str:
    paras = _docx_paragraphs(USTAWA)
    out = ["# Ustawa z 21.11.2008 o służbie cywilnej — wybrane przepisy\n"]
    current, buf = None, []
    for p in paras:
        m = re.match(r"Art\. (\d+[a-z]?)\b", p.replace("\xa0", " "))
        if m:
            if current:
                out.append(f"## art. {current} ustawy o służbie cywilnej\n\n" + "\n".join(buf) + "\n")
            current, buf = m.group(1), [p]
        elif current:
            buf.append(p)
    if current:
        out.append(f"## art. {current} ustawy o służbie cywilnej\n\n" + "\n".join(buf) + "\n")
    return "\n".join(out)


def build_poradnik(max_chars: int = 1800) -> str:
    out = ["# Poradnik KPRM „Oceny okresowe w służbie cywilnej” (2016)\n"]
    for number, page in enumerate(_pdf_pages(PORADNIK), 1):
        if number <= 2:  # okładka i spis treści
            continue
        text = _clean(re.sub(r"^\s*\d+\s*\n", "", page))
        if len(text) < 80:
            continue
        chunks, buf = [], ""
        for para in text.split("\n"):
            if len(buf) + len(para) > max_chars and buf:
                chunks.append(buf)
                buf = ""
            buf = f"{buf}\n{para}" if buf else para
        if buf:
            chunks.append(buf)
        for i, chunk in enumerate(chunks):
            suffix = f" (cz. {i + 1})" if len(chunks) > 1 else ""
            out.append(f"## Poradnik KPRM, s. {number}{suffix}\n\n{chunk.strip()}\n")
    return "\n".join(out)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, builder in (("rozporzadzenie", build_rozporzadzenie), ("ustawa", build_ustawa), ("poradnik", build_poradnik)):
        path = OUT / f"{name}.md"
        path.write_text(builder(), encoding="utf-8")
        print(f"{path.relative_to(ROOT)}: {path.stat().st_size} B")


if __name__ == "__main__":
    main()
