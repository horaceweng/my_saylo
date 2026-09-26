import httpx
import pytest

from app.services import news
from app.services.news import NewsError

BODY = [
    "The government announced on Tuesday that it would raise the minimum wage for workers across the country, a move that supporters say will help millions of families cope with the rising cost of living.",
    "Critics of the plan argued that small businesses would struggle to pay higher wages and might be forced to cut jobs or raise prices, which could hurt the very people the policy is meant to help.",
    "Economists were divided on the question. Some pointed to studies showing little effect on employment, while others warned that the results depend on how quickly the changes are introduced.",
    "The new rules will take effect in January, and officials said they would review the impact after one year before deciding whether any further increases are needed.",
]


def page(paragraphs=BODY, title="Minimum wage to rise next year", site="Example News", extra_head="", extra_body=""):
    ps = "".join(f"<p>{p}</p>" for p in paragraphs)
    return f"""<html lang="en"><head><title>{title} - {site}</title>
<meta property="og:title" content="{title}"><meta property="og:site_name" content="{site}">
<meta property="og:image" content="https://img.example.com/wage.jpg">
<meta property="article:published_time" content="2026-09-24T08:30:00Z"><meta name="author" content="Jane Reporter">{extra_head}</head>
<body><header><nav><a href="/">Home</a><a href="/world">World</a><a href="/sport">Sport</a></nav></header>
<main><article><h1>{title}</h1><div class="byline">By Jane Reporter</div>{ps}{extra_body}</article></main>
<aside><h3>Most read</h3><ul><li><a href="/a">Other story one</a></li><li><a href="/b">Other story two</a></li></ul></aside>
<footer><p>Copyright Example News. All rights reserved.</p><a href="/privacy">Privacy</a></footer></body></html>"""


def test_the_article_is_pulled_out_of_the_page_furniture():
    a = news.extract_article(page(), "https://www.example.com/news/wage?utm_source=x")
    assert a.title == "Minimum wage to rise next year" and a.site == "Example News" and a.published == "2026-09-24"
    assert a.image == "https://img.example.com/wage.jpg" and a.url == "https://www.example.com/news/wage"
    text = " ".join(a.paragraphs)
    assert "raise the minimum wage" in text and "review the impact after one year" in text
    for junk in ("Most read", "Other story", "Copyright Example News", "Privacy", "Home"):
        assert junk not in text
    assert len(a.paragraphs) == 4


def test_page_furniture_lines_and_a_repeated_headline_are_dropped():
    cleaned = news.clean_paragraphs("Minimum wage to rise\n- Published\nMinimum wage to rise\nGetty Images\nReal sentence goes here.\nReal sentence goes here.\nShare", "Minimum wage to rise")
    assert cleaned == ["Real sentence goes here."]
    dividers = news.clean_paragraphs("First real paragraph.\n____________________________________\n- - - - -\n***\nSecond real paragraph.", "T")
    assert dividers == ["First real paragraph.", "Second real paragraph."]


def test_leftovers_of_link_markup_are_cleaned_up():
    cleaned = news.clean_paragraphs("Reports from The Athletic , externalis that the panel has decided , and it was clear .\nSee the Times, external, for more.\nA normal sentence, with an externally funded study.", "T")
    assert cleaned == ["Reports from The Athletic is that the panel has decided, and it was clear.", "See the Times, for more.", "A normal sentence, with an externally funded study."]


def test_a_page_with_hardly_any_text_or_not_in_english_is_refused_with_a_reason():
    with pytest.raises(NewsError, match="只有 \\d+ 個字"):
        news.extract_article(page(["Watch the video."]), "https://a.com/v")
    with pytest.raises(NewsError, match="抓不到"):
        news.extract_article("<html><body></body></html>", "https://a.com/x")
    french = [
        "Le gouvernement a annoncé mardi qu'il augmenterait le salaire minimum pour les travailleurs dans tout le pays, une mesure qui aidera des millions de familles à faire face à la hausse du coût de la vie.",
        "Les critiques du projet ont affirmé que les petites entreprises auraient du mal à payer des salaires plus élevés et pourraient être obligées de supprimer des emplois ou d'augmenter leurs prix.",
        "Les économistes étaient divisés sur la question. Certains ont cité des études montrant peu d'effet sur l'emploi, tandis que d'autres ont averti que les résultats dépendent de la rapidité des changements.",
        "Les nouvelles règles entreront en vigueur en janvier, et les responsables ont déclaré qu'ils examineraient l'impact après un an avant de décider si d'autres augmentations sont nécessaires.",
    ]
    with pytest.raises(NewsError, match="不是英文"):
        news.extract_article(page(french), "https://a.com/fr")


def test_english_detection():
    assert news.looks_english("The cat sat on the mat and it was happy with the world.")
    assert not news.looks_english("Le chat est assis sur le tapis et il est heureux de vivre.")
    assert not news.looks_english("这是一段中文文字，完全不是英文。" * 5)
    assert not news.looks_english("")


def test_tracking_parameters_do_not_make_a_second_article():
    a = "https://www.bbc.co.uk/news/articles/abc?at_medium=RSS&at_campaign=rss#comments"
    b = "https://WWW.bbc.co.uk/news/articles/abc"
    assert news.canonical_url(a) == news.canonical_url(b) == "https://www.bbc.co.uk/news/articles/abc"
    assert news.url_key(a) == news.url_key(b)
    assert news.canonical_url("https://a.com/p?id=7&utm_source=x") == "https://a.com/p?id=7"  # a real parameter stays


@pytest.mark.parametrize("bad", ["", "not a url", "ftp://a.com/x", "file:///etc/passwd", "javascript:alert(1)"])
def test_only_web_links_are_accepted(bad):
    with pytest.raises(NewsError):
        news.check_url(bad)


def test_fetching_reports_paywalls_missing_pages_and_network_errors():
    def client(handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    assert news.fetch_html("https://a.com/x", client(lambda r: httpx.Response(200, text="<html>hi</html>"))) == "<html>hi</html>"
    with pytest.raises(NewsError, match="付費牆"):
        news.fetch_html("https://a.com/x", client(lambda r: httpx.Response(403)))
    with pytest.raises(NewsError, match="HTTP 404"):
        news.fetch_html("https://a.com/x", client(lambda r: httpx.Response(404)))

    def boom(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(NewsError, match="連不上"):
        news.fetch_html("https://a.com/x", client(boom))


RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>Example Feed</title>
<item><title>First story</title><link>https://a.com/1?utm_source=rss</link><pubDate>Thu, 24 Sep 2026 08:30:00 GMT</pubDate><description>&lt;p&gt;A &lt;b&gt;short&lt;/b&gt; summary.&lt;/p&gt;</description></item>
<item><title>Second story</title><link>https://a.com/2</link></item><item><title>No link</title></item></channel></rss>"""


def test_feed_items_have_title_link_date_and_a_plain_summary():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=RSS.encode())))
    title, items = news.read_feed("https://a.com/rss", client)
    assert title == "Example Feed" and [i.title for i in items] == ["First story", "Second story"]
    assert items[0].published == "2026-09-24" and items[0].summary == "A short summary."


def test_something_that_is_not_a_feed_is_refused():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<html><body>hello</body></html>")))
    with pytest.raises(NewsError, match="不是有效的 RSS"):
        news.read_feed("https://a.com/page", client)
    with pytest.raises(NewsError, match="HTTP 500"):
        news.read_feed("https://a.com/rss", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500))))
