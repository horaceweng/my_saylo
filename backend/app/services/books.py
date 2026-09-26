"""Turn an EPUB or a plain-text book into chapters of paragraphs."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from bs4 import BeautifulSoup

MAX_PARAGRAPH_CHARS = 1200  # longer ones are cut at sentence ends: easier to read, and to translate
MIN_CHAPTER_WORDS = 30  # shorter "chapters" are covers, dedications, blank pages
PARAGRAPHS_PER_PART = 40  # when a text has no chapter headings, it is cut into parts of this size


class BookError(ValueError):
    """The file cannot be read as a book; the message says why."""


@dataclass
class ParsedChapter:
    title: str
    paragraphs: list[str] = field(default_factory=list)

    @property
    def words(self) -> int:
        return sum(len(p.split()) for p in self.paragraphs)


@dataclass
class ParsedBook:
    title: str
    author: str
    chapters: list[ParsedChapter]


# ---- shared helpers ------------------------------------------------------------------------

_SENTENCE = re.compile(r"""[^\n]*?[.!?…]["'”’)\]]*(?=\s+["'“‘(\[]*[A-Z0-9]|\s*$)""", re.S)
_ABBREVIATION = re.compile(r"\b(?:Mr|Mrs|Ms|Messrs|Dr|St|Prof|Sr|Jr|Mt|vs|Capt|Col|Gen|Lt|Sgt|Rev|Hon|No|Mme|Mlle|M)\.[\"'”’)\]]*$")


def sentences(text: str) -> list[str]:
    """Split running text into sentences; "Mr. Smith" is not broken after "Mr."."""
    found: list[str] = []
    position = 0
    for match in _SENTENCE.finditer(text):
        piece = match.group().strip()
        position = match.end()
        if not piece:
            continue
        if found and _ABBREVIATION.search(found[-1]):
            found[-1] = f"{found[-1]} {piece}"  # the previous "sentence" ended in an abbreviation
        else:
            found.append(piece)
    rest = text[position:].strip()
    if rest:
        found.append(f"{found.pop()} {rest}" if found and _ABBREVIATION.search(found[-1]) else rest)
    return found


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace(" ", " ")).strip()


def split_long(paragraph: str, limit: int = MAX_PARAGRAPH_CHARS) -> list[str]:
    """Cut a very long paragraph at sentence ends into pieces no longer than `limit` (when possible)."""
    if len(paragraph) <= limit:
        return [paragraph]
    pieces, current = [], ""
    for sentence in sentences(paragraph):
        if current and len(current) + 1 + len(sentence) > limit:
            pieces.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        pieces.append(current)
    return pieces


_BOILERPLATE = re.compile(r"project gutenberg|gutenberg-tm|gutenberg literary archive|www\.gutenberg\.org", re.I)


_FRONT_MATTER = re.compile(
    r"^(?:Title|Author|Editor|Illustrator|Translator|Release date|Language|Credits|Produced by|Most recently updated|"
    r"Character set encoding|Original publication|Note)\s*:", re.I
)
_NUMERAL_ONLY = re.compile(r"^(?:[IVXLCDM]+|\d+)\.?$")
_NOT_CHAPTERS = re.compile(r"^(?:table of )?contents$|^index$|gutenberg|list of illustrations", re.I)
_CAPTION = re.compile(r"^\[(?:[^\]]*)(?:Copyright|Illustration)[^\]]*\]$", re.I)  # "[Copyright 1894 by George Allen.]"
_TRAILING_CHAPTER = re.compile(r"\b(CHAPTER\s+(?:[IVXLCDM]+|\d+)\.?)\s*$", re.I)


def title_key(text: str) -> str:
    """A form of a title for comparing: "D R A C U L A", "Dracula." and "dracula" are the same."""
    return re.sub(r"[^a-z0-9]", "", text.lower())


def is_boilerplate(text: str) -> bool:
    return len(_BOILERPLATE.findall(text)) >= 2 or bool(re.search(r"\*\*\*\s*(START|END) OF", text))


def finalize(book: ParsedBook) -> ParsedBook:
    """Drop empty and trivial chapters, split overlong paragraphs, give chapters usable names."""
    chapters: list[ParsedChapter] = []
    for chapter in book.chapters:
        if _NOT_CHAPTERS.search(clean(chapter.title)):
            continue  # contents pages, indexes, the license
        paragraphs = [
            p for para in chapter.paragraphs if not _FRONT_MATTER.match(clean(para)) for p in split_long(clean(para)) if p
        ]
        candidate = ParsedChapter(chapter.title, paragraphs)
        if candidate.words < MIN_CHAPTER_WORDS:
            continue
        if chapters and title_key(chapter.title) and title_key(chapter.title) == title_key(chapters[-1].title):
            chapters[-1].paragraphs += paragraphs  # the same heading again (a running title): one chapter
        else:
            chapters.append(candidate)
    parent = ""
    for i, chapter in enumerate(chapters, start=1):
        title = clean(chapter.title)
        if _NUMERAL_ONLY.match(title) and parent:
            title = f"{parent} · {title.rstrip('.')}"  # "II." inside "A Scandal in Bohemia"
        elif title and not _NUMERAL_ONLY.match(title):
            parent = title
        chapter.title = title[:200] or f"第 {i} 章"
    if not chapters:
        raise BookError("這個檔案裡找不到可閱讀的英文內容")
    return ParsedBook(clean(book.title)[:300] or "Untitled", clean(book.author)[:200], chapters)


# ---- EPUB ----------------------------------------------------------------------------------

_HEADINGS = {"h1", "h2", "h3"}


def _toc_titles(book) -> dict[str, str]:
    """document file name → the title the book's table of contents gives it. Entries that point inside a
    document ("#illustration-3") are ignored: they name a place, not the document, and would rename its chapter."""
    titles: dict[str, str] = {}

    def walk(nodes):
        for node in nodes:
            if isinstance(node, tuple):  # (Section, [children])
                section, children = node
                href = getattr(section, "href", "") or ""
                if href and "#" not in href:
                    titles.setdefault(href, section.title)
                walk(children)
            else:
                href = getattr(node, "href", "") or ""
                if href and "#" not in href:
                    titles.setdefault(href, node.title)

    walk(book.toc)
    return titles


def parse_epub(path: Path) -> ParsedBook:
    from ebooklib import ITEM_DOCUMENT, epub

    try:
        book = epub.read_epub(str(path), options={"ignore_ncx": True})
    except Exception as e:  # noqa: BLE001 - ebooklib raises many kinds of errors for bad files
        raise BookError(f"無法讀取這個 EPUB：{e}") from e
    titles = _toc_titles(book)
    metadata = lambda key: (book.get_metadata("DC", key) or [("", {})])[0][0]  # noqa: E731
    book_key = title_key(metadata("title"))
    chapters: list[ParsedChapter] = []
    for item_id, _ in book.spine:
        item = book.get_item_with_id(item_id)
        if item is None or item.get_type() != ITEM_DOCUMENT:
            continue
        soup = BeautifulSoup(item.get_content(), "lxml")
        for tag in soup(["script", "style", "nav"]):
            tag.decompose()
        body = soup.body or soup
        if is_boilerplate(body.get_text(" ", strip=True)[:4000]) and len(body.get_text()) < 20000:
            continue  # the Project Gutenberg header and license pages
        default_title = titles.get(item.get_name(), "")
        if title_key(default_title) == book_key:
            default_title = ""  # the contents page names the whole book, not a chapter
        if not default_title and chapters:
            current = chapters[-1]  # a document with no name of its own continues the chapter before it
        else:
            current = ParsedChapter(default_title)
            chapters.append(current)
        elements = body.find_all(["p", *_HEADINGS])
        if not any(e.name == "p" for e in elements):  # some books use plain <div>s
            elements = body.find_all(["div", *_HEADINGS])
        for element in elements:
            if element.name != "p" and element.name not in _HEADINGS and element.find(["p", "div"]):
                continue  # a container; its children are handled themselves
            for br in element.find_all("br"):
                br.replace_with(" ")
            text = clean(element.get_text())  # no separator: a drop cap "T" + "o" must stay "To"
            if not text:
                continue
            if element.name in _HEADINGS:
                if title_key(text) == book_key or title_key(text) == "":
                    continue  # the running title of the book, repeated on every page
                tail = _TRAILING_CHAPTER.search(text)
                if tail and len(text) > len(tail.group(1)) + 3:
                    text = tail.group(1)  # an illustration caption run together with the chapter heading
                if current.paragraphs:  # a heading inside a document starts a new chapter
                    current = ParsedChapter(text)
                    chapters.append(current)
                elif not current.title or (_looks_like_heading(text) and not _looks_like_heading(current.title)):
                    current.title = text  # a real chapter heading beats a caption or the contents page's name
                continue
            if _CAPTION.match(text):
                continue
            if not is_boilerplate(text) and text.lower().rstrip(".:") not in ("contents", "table of contents"):
                current.paragraphs.append(text)
    return finalize(ParsedBook(metadata("title"), metadata("creator"), chapters))


# ---- plain text ----------------------------------------------------------------------------

_START = re.compile(r"\*\*\*\s*START OF (?:THE|THIS) PROJECT GUTENBERG EBOOK.*?\*\*\*", re.I | re.S)
_END = re.compile(r"\*\*\*\s*END OF (?:THE|THIS) PROJECT GUTENBERG EBOOK", re.I)
_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|"
    "twenty|thirty|forty|fifty|first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth|eleventh|twelfth|last|final"
)
# "CHAPTER 12", "Chapter the First", "BOOK ONE: 1805", "Part IV - Home": the keyword must be followed by a number
_HEADING = re.compile(
    rf"^(?:CHAPTER|BOOK|PART|LETTER|STAVE|ACT|SECTION|VOLUME|CANTO|SCENE)\s+(?:the\s+)?(?:[IVXLCDM]+|\d+|{_NUMBER_WORDS})\b.{{0,90}}$",
    re.I,
)


def _looks_like_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 100:
        return False
    if re.fullmatch(r"[IVXLCDM]{1,8}\.?|\d{1,3}\.?", line, re.I):
        return line.rstrip(".").isupper() or line.rstrip(".").isdigit()  # "IV." but not the pronoun "I" in lower case
    return bool(_HEADING.match(line))


def parse_text(text: str, fallback_title: str = "") -> ParsedBook:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    title = author = ""
    if m := re.search(r"^Title:\s*(.+)$", text, re.M):
        title = m.group(1).strip()
    if m := re.search(r"^Author:\s*(.+)$", text, re.M):
        author = m.group(1).strip()
    if start := _START.search(text):
        text = text[start.end():]
    if end := _END.search(text):
        text = text[: end.start()]
    chapters: list[ParsedChapter] = [ParsedChapter("")]
    for block in re.split(r"\n\s*\n", text):
        lines = [ln.strip() for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        if sum(1 for ln in lines if _looks_like_heading(ln)) >= 3:
            continue  # a table of contents listing many headings in one block
        one_line = clean(" ".join(lines))
        if _looks_like_heading(lines[0]) and len(one_line) <= 100:
            chapters.append(ParsedChapter(one_line))
        elif not is_boilerplate(one_line):
            chapters[-1].paragraphs.append(one_line)
    if sum(1 for c in chapters if c.title and c.paragraphs) < 2:  # no usable headings: cut into parts
        paragraphs = [p for c in chapters for p in c.paragraphs]
        chapters = [ParsedChapter(f"Part {i // PARAGRAPHS_PER_PART + 1}") for i in range(0, len(paragraphs), PARAGRAPHS_PER_PART)]
        for i, para in enumerate(paragraphs):
            chapters[i // PARAGRAPHS_PER_PART].paragraphs.append(para)
    return finalize(ParsedBook(title or fallback_title, author, chapters))
