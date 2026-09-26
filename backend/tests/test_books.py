import pytest
from ebooklib import epub

from app.services import books
from app.services.books import BookError

LOREM = (
    "It was a bright cold day in April, and the clocks were striking thirteen. "
    "Winston Smith slipped quickly through the glass doors of the building, though not quickly enough to prevent a swirl of gritty dust."
)


def para(n=1):
    return " ".join([LOREM] * n)


def make_epub(tmp_path, docs, toc=None, title="A Test Book", author="Ann Author", name="book.epub"):
    """docs: list of (file name, html body). toc: {file name: title} for the table of contents."""
    book = epub.EpubBook()
    book.set_identifier("id-1")
    book.set_title(title)
    book.set_language("en")
    book.add_author(author)
    items = []
    for fname, body in docs:
        item = epub.EpubHtml(title=(toc or {}).get(fname, ""), file_name=fname, lang="en")
        item.content = f"<html><body>{body}</body></html>"
        book.add_item(item)
        items.append(item)
    book.toc = [epub.Link(i.file_name, (toc or {})[i.file_name], i.file_name) for i in items if toc and i.file_name in toc]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", *items]
    path = tmp_path / name
    epub.write_epub(str(path), book)
    return path


def test_epub_chapters_follow_the_spine_and_use_the_table_of_contents_names(tmp_path):
    path = make_epub(
        tmp_path,
        [("c1.xhtml", f"<h2>ignored heading</h2><p>{para()}</p><p>{para()}</p>"), ("c2.xhtml", f"<p>{para(2)}</p>")],
        toc={"c1.xhtml": "The Beginning", "c2.xhtml": "The Middle"},
    )
    book = books.parse_epub(path)
    assert (book.title, book.author) == ("A Test Book", "Ann Author")
    assert [c.title for c in book.chapters] == ["The Beginning", "The Middle"]
    assert [len(c.paragraphs) for c in book.chapters] == [2, 1]


def test_epub_without_a_table_of_contents_takes_titles_from_headings(tmp_path):
    path = make_epub(tmp_path, [("a.xhtml", f"<h1>Chapter One</h1><p>{para()}</p>"), ("b.xhtml", f"<h1>Chapter Two</h1><p>{para()}</p>")])
    assert [c.title for c in books.parse_epub(path).chapters] == ["Chapter One", "Chapter Two"]


def test_a_heading_inside_one_document_starts_a_new_chapter(tmp_path):
    body = f"<h2>I</h2><p>{para()}</p><p>{para()}</p><h2>II</h2><p>{para()}</p><h2>III</h2><p>{para()}</p>"
    book = books.parse_epub(make_epub(tmp_path, [("all.xhtml", body)]))
    assert [c.title for c in book.chapters] == ["I", "II", "III"]
    assert [len(c.paragraphs) for c in book.chapters] == [2, 1, 1]


def test_gutenberg_header_and_license_pages_are_left_out(tmp_path):
    header = "<p>The Project Gutenberg eBook of A Test Book, by Ann Author</p><p>This eBook is for the use of anyone anywhere. Project Gutenberg License included.</p>"
    footer = "<p>*** END OF THE PROJECT GUTENBERG EBOOK A TEST BOOK ***</p><p>Project Gutenberg-tm depends upon donations. www.gutenberg.org</p>"
    path = make_epub(tmp_path, [("h.xhtml", header), ("c.xhtml", f"<h2>One</h2><p>{para()}</p>"), ("f.xhtml", footer)])
    book = books.parse_epub(path)
    assert [c.title for c in book.chapters] == ["One"]
    assert not any("Gutenberg" in p for c in book.chapters for p in c.paragraphs)


def test_covers_dedications_and_blank_pages_are_not_chapters(tmp_path):
    path = make_epub(tmp_path, [("cover.xhtml", "<p>Cover</p>"), ("ded.xhtml", "<p>To my mother.</p>"), ("c.xhtml", f"<h2>One</h2><p>{para()}</p>")])
    assert [c.title for c in books.parse_epub(path).chapters] == ["One"]


def test_books_that_use_divs_instead_of_paragraphs_still_read(tmp_path):
    path = make_epub(tmp_path, [("c.xhtml", f"<h2>One</h2><div>{para()}</div><div>{para()}</div>")])
    assert len(books.parse_epub(path).chapters[0].paragraphs) == 2


def test_a_file_that_is_not_an_epub_or_has_no_text_is_refused_with_a_message(tmp_path):
    bad = tmp_path / "x.epub"
    bad.write_bytes(b"not a zip")
    with pytest.raises(BookError, match="無法讀取"):
        books.parse_epub(bad)
    with pytest.raises(BookError, match="找不到可閱讀"):
        books.parse_epub(make_epub(tmp_path, [("e.xhtml", "<p>hi</p>")], name="empty.epub"))


# ---- plain text ----------------------------------------------------------------------------

GUTENBERG_TEXT = f"""The Project Gutenberg eBook of A Test Book

Title: A Test Book
Author: Ann Author

*** START OF THE PROJECT GUTENBERG EBOOK A TEST BOOK ***

CONTENTS

CHAPTER I. The Start
CHAPTER II. The Next Thing
CHAPTER III. The End


CHAPTER I. The Start

{LOREM}
continues here on a wrapped
line of the same paragraph.

{LOREM}


CHAPTER II. The Next Thing

{LOREM}

{LOREM}


CHAPTER III. The End

{LOREM}

*** END OF THE PROJECT GUTENBERG EBOOK A TEST BOOK ***

License text: Project Gutenberg-tm and www.gutenberg.org rules.
"""


def test_gutenberg_text_is_stripped_of_header_footer_and_contents_and_split_into_chapters():
    book = books.parse_text(GUTENBERG_TEXT)
    assert (book.title, book.author) == ("A Test Book", "Ann Author")
    assert [c.title for c in book.chapters] == ["CHAPTER I. The Start", "CHAPTER II. The Next Thing", "CHAPTER III. The End"]
    first = book.chapters[0].paragraphs
    assert len(first) == 2 and "wrapped line of the same paragraph." in first[0]  # wrapped lines are joined
    assert not any("Gutenberg" in p or "License" in p for c in book.chapters for p in c.paragraphs)


def test_roman_numeral_headings_work_too():
    text = "\n\n".join(f"{n}.\n\n{LOREM}\n\n{LOREM}" for n in ["I", "II", "III"])
    assert [c.title for c in books.parse_text(text).chapters] == ["I.", "II.", "III."]


def test_text_without_headings_is_cut_into_parts():
    text = "\n\n".join(LOREM for _ in range(95))
    book = books.parse_text(text, fallback_title="Loose Text")
    assert book.title == "Loose Text" and [c.title for c in book.chapters] == ["Part 1", "Part 2", "Part 3"]
    assert [len(c.paragraphs) for c in book.chapters] == [40, 40, 15]


def test_an_ordinary_sentence_starting_with_a_capital_is_not_taken_for_a_heading():
    text = f"Chapter One\n\n{LOREM}\n\nPart of the problem was that nobody knew.\n\n{LOREM}\n\nChapter Two\n\n{LOREM}"
    book = books.parse_text(text)
    assert [c.title for c in book.chapters] == ["Chapter One", "Chapter Two"]
    assert "Part of the problem was that nobody knew." in book.chapters[0].paragraphs


def test_empty_text_is_refused():
    with pytest.raises(BookError):
        books.parse_text("   \n\n  ")


def test_long_paragraphs_are_cut_at_sentence_ends():
    long = " ".join(f"Sentence number {i} is here." for i in range(200))
    pieces = books.split_long(long)
    assert all(len(p) <= books.MAX_PARAGRAPH_CHARS for p in pieces) and " ".join(pieces) == long
    assert all(p.endswith(".") for p in pieces)


def test_a_paragraph_that_fits_is_left_alone_and_abbreviations_do_not_end_sentences():
    assert books.split_long("Short one.") == ["Short one."]
    assert books.sentences("Mr. Smith met Dr. Jones. They talked.") == ["Mr. Smith met Dr. Jones.", "They talked."]


@pytest.mark.parametrize("line", ["CHAPTER I", "Chapter 12", "CHAPTER XII. The Trial", "Chapter the First", "BOOK ONE: 1805", "PART IV - Home", "Chapter Twenty-One", "IV.", "12.", "I"])  # a lone "I" on its own line is a chapter number
def test_real_headings_are_recognised(line):
    assert books._looks_like_heading(line)


@pytest.mark.parametrize("line", ["Part of the problem was that nobody knew.", "Chapters were short.", "Book learning is not enough", "Act now, said the man.", "i", "The End", "It was late."])
def test_ordinary_lines_are_not_headings(line):
    assert not books._looks_like_heading(line)


def test_a_document_without_a_name_continues_the_previous_chapter(tmp_path):
    path = make_epub(tmp_path, [("a.xhtml", f"<h2>Chapter I.</h2><p>{para()}</p>"), ("b.xhtml", f"<p>{para()}</p><p>{para()}</p>"), ("c.xhtml", f"<h2>Chapter II.</h2><p>{para()}</p>")])
    book = books.parse_epub(path)
    assert [c.title for c in book.chapters] == ["Chapter I.", "Chapter II."]
    assert [len(c.paragraphs) for c in book.chapters] == [3, 1]


def test_repeated_book_title_headings_and_metadata_lines_are_not_chapters_or_text(tmp_path):
    body = (f"<h1>A TEST BOOK</h1><p>Title : A Test Book</p><p>Author : Ann Author</p><h2>Chapter One</h2><p>{para()}</p>"
            f"<h1>A Test Book</h1><h2>Chapter Two</h2><p>{para()}</p>")
    book = books.parse_epub(make_epub(tmp_path, [("all.xhtml", body)]))
    assert [c.title for c in book.chapters] == ["Chapter One", "Chapter Two"]
    assert not any(p.startswith(("Title", "Author")) for c in book.chapters for p in c.paragraphs)


def test_an_illustration_caption_does_not_take_the_place_of_the_chapter_heading(tmp_path):
    body = (f"<h2>Chapter One</h2><p>{para()}</p>"
            f"<h3>\u201cHe came down to see the place\u201d</h3><h2>Chapter Two</h2><p>{para()}</p>"
            f"<h3>\u201cShe is tolerable\u201d CHAPTER III.</h3><p>{para()}</p>")
    assert [c.title for c in books.parse_epub(make_epub(tmp_path, [("all.xhtml", body)])).chapters] == ["Chapter One", "Chapter Two", "CHAPTER III."]


def test_contents_index_and_license_chapters_are_dropped(tmp_path):
    docs = [("t.xhtml", f"<h2>Contents</h2><p>{para()}</p>"), ("c.xhtml", f"<h2>One</h2><p>{para()}</p>"), ("i.xhtml", f"<h2>List of Illustrations</h2><p>{para()}</p>"),
            ("x.xhtml", f"<h2>Index</h2><p>{para()}</p>")]
    assert [c.title for c in books.parse_epub(make_epub(tmp_path, docs)).chapters] == ["One"]


def test_a_drop_cap_split_into_its_own_span_stays_one_word(tmp_path):
    body = f'<h2>One</h2><p><span class="dropcap">T</span>o Sherlock Holmes she is always the woman. {para()}</p>'
    assert books.parse_epub(make_epub(tmp_path, [("c.xhtml", body)])).chapters[0].paragraphs[0].startswith("To Sherlock")


def test_numeral_only_sections_are_named_after_the_story_they_belong_to(tmp_path):
    body = f"<h2>A Scandal in Bohemia</h2><p>{para()}</p><h3>II.</h3><p>{para()}</p><h3>III.</h3><p>{para()}</p><h2>The League</h2><p>{para()}</p>"
    titles = [c.title for c in books.parse_epub(make_epub(tmp_path, [("all.xhtml", body)])).chapters]
    assert titles == ["A Scandal in Bohemia", "A Scandal in Bohemia · II", "A Scandal in Bohemia · III", "The League"]
