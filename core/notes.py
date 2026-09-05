from html.parser import HTMLParser

from django.utils.html import escape

_ALLOWED_TAGS = {
    "b",
    "strong",
    "i",
    "em",
    "u",
    "s",
    "ul",
    "ol",
    "li",
    "p",
    "br",
    "div",
    "span",
    "h3",
    "h4",
}


class _NoteSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._out = []

    def handle_starttag(self, tag, attrs):
        if tag not in _ALLOWED_TAGS:
            return
        self._out.append(f"<{tag}>")

    def handle_endtag(self, tag):
        if tag not in _ALLOWED_TAGS:
            return
        self._out.append(f"</{tag}>")

    def handle_data(self, data):
        self._out.append(escape(data))

    def result(self):
        return "".join(self._out)


def sanitize_note_html(raw):
    parser = _NoteSanitizer()
    parser.feed(raw or "")
    parser.close()
    return parser.result()[:20000]
