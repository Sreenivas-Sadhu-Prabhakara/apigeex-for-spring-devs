"""apolaki_pygments.py — a custom Pygments style for the Apolaki dark theme.

Apolaki is the Filipino sun/war deity; the palette is a charcoal night sky lit by
solar gold and ember, with war-red reserved for errors. The colours here are tuned
for high readability on the code background #14161B and to harmonise with the site's
CSS variables (see assets/style.css).

build.py renders this to docs/assets/pygments.css via:
    HtmlFormatter(style=ApolakiStyle).get_style_defs(".codehilite")
so the highlighting is class-based (Pygments emits <span class="k"> …); the colours
below become the stylesheet.
"""

from pygments.style import Style
from pygments.token import (
    Comment,
    Error,
    Generic,
    Keyword,
    Literal,
    Name,
    Number,
    Operator,
    Punctuation,
    String,
    Text,
    Token,
    Whitespace,
)

# ---- Apolaki palette ----------------------------------------------------------
BG = "#14161B"          # charcoal code background
FG = "#ECEDEE"          # primary text
GOLD = "#F5A524"        # solar gold — keywords, tags
GOLD_SOFT = "#FFC14D"   # lighter gold — functions, attributes
EMBER = "#FF6B1A"       # ember — strings
EMBER_SOFT = "#FF9457"  # soft ember — string escapes, chars
RED = "#E03131"         # war red — errors
TEAL = "#5BC8C0"        # cool counterpoint — numbers, constants
SKY = "#7FB2F0"         # cool blue — class/namespace names
MUTED = "#7A8290"       # muted slate — comments, punctuation
LILAC = "#C8A2F0"       # decorators, builtins
GREEN = "#7FD18B"       # inserted/diff-add, booleans


class ApolakiStyle(Style):
    """Solar-on-charcoal highlighting for Apigee XML, bash, JS, JSON, and Java."""

    name = "apolaki"
    background_color = BG
    highlight_color = "#2A2E37"
    line_number_color = MUTED
    line_number_background_color = BG

    styles = {
        Token: FG,
        Text: FG,
        Whitespace: "",
        Error: f"bold {RED}",

        Comment: f"italic {MUTED}",
        Comment.Preproc: LILAC,
        Comment.Special: f"italic bold {MUTED}",

        Keyword: f"bold {GOLD}",
        Keyword.Constant: TEAL,
        Keyword.Declaration: f"bold {GOLD}",
        Keyword.Namespace: f"bold {EMBER}",
        Keyword.Type: GOLD_SOFT,

        Operator: EMBER_SOFT,
        Operator.Word: f"bold {GOLD}",
        Punctuation: "#B9BEC8",

        Name: FG,
        Name.Attribute: GOLD_SOFT,
        Name.Builtin: LILAC,
        Name.Builtin.Pseudo: LILAC,
        Name.Class: f"bold {SKY}",
        Name.Constant: TEAL,
        Name.Decorator: LILAC,
        Name.Entity: EMBER_SOFT,
        Name.Exception: f"bold {RED}",
        Name.Function: GOLD_SOFT,
        Name.Label: TEAL,
        Name.Namespace: SKY,
        Name.Tag: f"bold {GOLD}",
        Name.Variable: FG,
        Name.Variable.Class: SKY,
        Name.Variable.Instance: FG,

        Number: TEAL,
        Literal: TEAL,
        Literal.Date: GREEN,

        String: EMBER,
        String.Backtick: EMBER_SOFT,
        String.Char: EMBER_SOFT,
        String.Doc: f"italic {MUTED}",
        String.Double: EMBER,
        String.Escape: f"bold {EMBER_SOFT}",
        String.Interpol: f"bold {GOLD_SOFT}",
        String.Regex: TEAL,
        String.Single: EMBER,
        String.Symbol: TEAL,

        Generic.Deleted: RED,
        Generic.Emph: "italic",
        Generic.Error: RED,
        Generic.Heading: f"bold {FG}",
        Generic.Inserted: GREEN,
        Generic.Output: MUTED,
        Generic.Prompt: f"bold {GOLD}",
        Generic.Strong: "bold",
        Generic.Subheading: f"bold {GOLD_SOFT}",
        Generic.Traceback: RED,
    }
