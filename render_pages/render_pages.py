"""Render the site's pages by wrapping each content fragment in base.html.

For every entry in PAGES, `render_pages/<name>_.html` holds the page content and
the result is written to `<repo root>/<name>.html`.
"""
from dataclasses import dataclass
import os

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.dirname(SRC_DIR)

# (key, href, label) of the navbar links after "Home". Comment out an entry to
# hide it from the navbar.
NAV_ITEMS = [
    # ("publications", "/publications.html", "Publication(s)"),
    ("resume", "/resume.html", "Resume"),
    ("contact", "/contact.html", "Contact"),
    ("recommendations", "/recommendations.html", "Recommendations"),
    # ("blog", "/blog.html", "Blog"),
    # ("about", "/about.html", "About Me"),
]

NAV_ITEM_TEMPLATE = """\
          <li class="nav-item">
            <a class="{css_class}" href="{href}">{label}</a>
          </li>"""

COLUMN_CLASS = "col-lg-{width} col-sm-12 col-md-11"
# Blank space at the bottom of long pages, so the text doesn't end at the very
# bottom of the window.
BOTTOM_SPACING_LINES = 9


@dataclass
class Page:
    name: str  # path of the page without extension, relative to the repo root
    nav_key: str  # navbar entry highlighted on this page
    width: int = 10  # Bootstrap column width on large screens
    bottom_spacing: int = 0  # number of trailing <br>s


def blog_post(name):
    return Page("blogs/" + name, "blog", bottom_spacing=BOTTOM_SPACING_LINES)


PAGES = [
    Page("about", "about", width=8),
    Page("blog", "blog"),
    Page("contact", "contact", width=8),
    Page("index", "home", bottom_spacing=4),
    Page("publications", "publications", width=11),
    Page("recommendations", "recommendations", width=11, bottom_spacing=BOTTOM_SPACING_LINES),
    Page("resume", "resume", width=11),
    blog_post("thinking_outside_the_box"),
    blog_post("you_gotta_have_steel_in_the_wall"),
    blog_post("kral_ciplak"),
    blog_post("maniler"),
    blog_post("iran_izlenimleri"),
]


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def nav_class(key, active_key, default):
    # The current page's link is highlighted by styling it as the navbar brand.
    return "navbar-brand" if key == active_key else default


def render_nav_items(active_key):
    return "\n".join(
        NAV_ITEM_TEMPLATE.format(css_class=nav_class(key, active_key, "nav-link"), href=href, label=label)
        for key, href, label in NAV_ITEMS
    )


def fill(template, **values):
    for key, value in values.items():
        placeholder = "{{" + key + "}}"
        if placeholder not in template:
            raise ValueError(f"Placeholder {placeholder} not found in template")
        template = template.replace(placeholder, value)
    return template


def render(base, page):
    content = read(os.path.join(SRC_DIR, page.name + "_.html")).strip("\n")
    return fill(
        base,
        home_class=nav_class("home", page.nav_key, "nav-link"),
        nav_items=render_nav_items(page.nav_key),
        column_class=COLUMN_CLASS.format(width=page.width),
        content=content,
        bottom_spacing="\n".join(["        <br>"] * page.bottom_spacing),
    )


def main():
    base = read(os.path.join(SRC_DIR, "base.html"))
    for page in PAGES:
        out_path = os.path.join(OUT_DIR, page.name + ".html")
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(render(base, page))
        print(out_path + " is saved")


if __name__ == "__main__":
    main()
