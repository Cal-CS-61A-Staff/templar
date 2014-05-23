import html
import re
from random import randint
from hashlib import sha1

TAB_SIZE = 4
SALT = bytes(randint(0, 1000000))
def hash_text(s, label):
    return label + '-' + sha1(SALT + s.encode("utf-8")).hexdigest() + '-' + label

def convert(text):
    text, variables = get_variables(text)
    text, references = get_references(text)
    text = handle_whitespace(text)
    hashes = {}
    text = hash_blocks(text, hashes)
    text = hash_lists(text, hashes)
    text = hash_blockquotes(text, hashes)
    text = hash_codeblocks(text, hashes)
    text = hash_codes(text, hashes)
    text = hash_inline_links(text, hashes)
    text = hash_reference_links(text, hashes, references)
    text = hash_tags(text, hashes)
    text = hr_re.sub(hr_sub, text)
    text = emphasis_re.sub(emphasis_sub, text)
    text = escape_re.sub(escapes_sub, text)
    text = auto_escape_re.sub(auto_escape_sub, text)
    text = atx_header_re.sub(atx_header_sub, text)
    text = setext_header_re.sub(setext_header_sub, text)
    text = paragraph_re.sub(paragraph_sub, text)
    text = unhash(text, hashes)
    text = slug_re.sub(slug_sub, text)
    return text, variables

##################
# Pre-Processing #
##################

re_retab = re.compile(r"""
([^\t]*?)   # \1 is string before the tab(s)
(\t+)       # \2 is consecutive string of tabs
""", re.M)
def sub_retab(match):
    r"""Remove all tabs and convert them into spaces.

    PARAMETERS:
    match -- regex match; uses re_retab pattern: \1 is text before tab,
             \2 is a consecutive string of tabs.

    A simple substitution of 4 spaces would result in the following:

        to\tlive    # original
        to    live  # simple substitution

    Instead, we convert tabs like the following:

        to\tlive    # original
        to  live    # the tab *looks* like two spaces, so we convert
                    # it to two spaces
    """
    before = match.group(1)
    tabs = len(match.group(2))
    return before + (' ' * (TAB_SIZE * tabs - len(before) % TAB_SIZE))
re_whitespace = re.compile(r'^\s+$', re.M)
def handle_whitespace(text):
    r"""Handles whitespace cleanup.

    Tabs are "smartly" retabbed (see sub_retab). Lines that contain
    only whitespace are truncated to a single newline.
    """
    text = re_retab.sub(sub_retab, text)
    text = re_whitespace.sub('', text).strip()
    return text

re_vars = re.compile(r"""
(?:\n|\A)   # beginning of line or string
~[ \t]+     # ~ followed by at least one space
(.*?)       # \1 is variable name
:[ \t]*     # variable name followed by colon and spaces
(.*?)$      # \2 is value
""", re.X | re.M | re.S)
def get_variables(text):
    """Extracts variables that can be used in templating engines.

    Each variable is defined on a single line in the following way:

        ~ var: text

    The ~ must be at the start of a newline, followed by at least one
    space. var can be any sequence of characters that does not contain
    a ":". text can be any sequence of characters.

    RETURNS:
    text      -- str; text with all variable definitions removed
    variables -- dict; variable to value mappings
    """
    variables = {var: value for var, value in re_vars.findall(text)}
    text = re_vars.sub('', text)
    return text, variables

re_references = re.compile(r"""
\n[ ]{0,3}              # up to three spaces
\[
    ([^\n]+?)           # \1 is reference id
\]:                     # square brackets followed immediately by colon
[ ]+
(.+?)                   # \2 is URL
\s
(?:                     # captures title
    [ \t]*\n?[ \t]*     # can only contain one newline
    (["'])              # \3 is style of quote
    (.*?)               # \4 is title
    \3                  # closing quote
)?                      # title is optional)
""", re.X | re.S)
def get_references(text):
    """Retrieves all link references within the text.

    Link references can be defined anywhere in the text, and look like
    this:

        [id]: www.example.com "optional title"

    A link (either <a> or <img>) can then refer to the link reference:

        [this is a link][id]

    Link IDs are case insensitive. Link references are also removed
    from the text after they have been retrieved.

    RETURNS:
    text       -- str; text with all link labels removed
    references -- dict; link ids to (URL, title), where title is the
                  empty string if it is omitted.
    """
    references = {}
    for ref_id, link, _, title in re_references.findall(text):
        ref_id = re.sub(r'<(.*?)>', r'\1', ref_id).lower().strip()
        references[ref_id] = (link, title)
    text = re_references.sub('', text)
    return text, references


######################
# Hashed Conversions #
######################


block_tags = "blockquote|div|form|hr|noscript|ol|p|pre|table"
re_block = re.compile(r"""
(?:(?<=\n)|(?<=\A))     # begin with newline or start of string
<
    \s*
    (%s)                # \1 is block_tags
    (?:\s+.*?)          # any attributes
>
.*?                     # contents in block element
\n<                     # close must start at front of newline
    \s*/\s*
    \1                  # matching close tag
    \s*
>
""" % block_tags, re.S | re.X)
def hash_blocks(text, hashes):
    """Hashes HTML block tags.

    PARAMETERS:
    text   -- str; Markdown text
    hashes -- dict; a dictionary of all hashes, where keys are hashes
              and values are their unhashed versions.

    When HTML block tags are used, all content inside the tags is
    preserved as-is, without any Markdown processing. See block_tags
    for a list of block tags.
    """
    def sub(match):
        block = match.group(0)
        hashed = hash_text(block, 'block')
        hashes[hashed] = block
        return hashed
    return re_block.sub(sub, text)

re_list = r"""
(?:(?<=\n)|(?<=\A)) # newline or start of string
(?:
    [ ]{0,3}                # up to three spaces
    %s                      # list marker
    (?!\ %s\ )              # * * * is not a valid list
    [ ]                     # must have at least one space
    .+?                     # list item
    \n*                     # capture trailing newlines
    (?=                     # end of a list item
        \n\n(?![ ]{4}) |    # blank line without 4 spaces after
        \Z                  # end of string
    )
)+                          # capture multiple list items
"""
def hash_lists(text, hashes):
    """Hashes ordered and unordered lists.

    re_list captures as many consecutive list items as possible and
    groups them into one list. Before hashing the lists, the items
    are recursively converted from Markdown to HTML. Upon unhashing,
    the lists will be ready in their final form.

    An attempt at list formatting is done by adding two spaces to
    each list item. Since list conversion is a recursive process,
    each nested list will add an additional two spaces to list items.
    The only exception is for pre blocks -- these are "pulled out" of
    indentation when the list is unhashed.

    A note on implementation: Markdown syntax for list items is
    essentially the same, except everything is shifted to the right by
    four spaces. This assumption is made when recursively converting
    list items.

    List items that consist of only a single paragraph of text are
    "pulled out" of the paragraph (that is, the <p> tag is removed).
    This differs slightly from original Markdown syntax, which encloses
    list items in <p> tags if list items are separated by one or more
    blank lines.
    """
    for style, marker in (('u', '[+*-]'), ('o', r'\d+\.')):
        list_re = re.compile(re_list % (marker, marker), re.S | re.X)
        for lst in list_re.findall(text):
            items = re.split(r'(?:\n|\A) {0,3}%s ' % marker, lst)[1:]
            whole_list = ''
            for item in items:
                item = re.sub(r'^ {1,4}', '', item, flags=re.M)
                item = convert(item)[0]
                match = re.match('<p>(.*?)</p>', item, flags=re.S)
                if match and match.group(0) == item.strip():
                    item = match.group(1)
                whole_list += '<li>{}</li>\n'.format(item)
            whole_list = '<{0}l>\n{1}\n</{0}l>'.format(
                    style,
                    re.sub('^', '  ', whole_list.strip(), flags=re.M))
            hashed = hash_text(whole_list, 'list')
            hashes[hashed] = whole_list
            start = text.index(lst)
            end = start + len(lst)
            text = text[:start] + '\n' + hashed + '\n\n' + text[end:]
    return text

re_codeblock = re.compile(r"""
(?:(?<=\n)|(?<=\A))     # newline or start of string
(?:
    [ ]{4}              # at least four spaces
    .+?                 # contents of line
    (?:\n+|\Z)          # ends with 1+ newlines or end of string
)+
""", re.S | re.X)
def hash_codeblocks(text, hashes):
    """Hashes codeblocks (<pre> elements).

    Codeblocks are strictly defined to be (non-list) lines that are
    indented at least 4 spaces from the newline. Exactly 4 spaces will
    be stripped from the beginning of the line -- any leading
    whitespace after that is preserved.

    Codeblock lines that are separated only by blank lines will be
    included in the same codeblock (as will the intermediate newlines).

    Certain HTML entities (&, <, >, ", ') will always be escaped inside
    code blocks.

    Markdown defines code blocks to be <pre><code>, not just <pre>.
    Certain highlighting packages (like highlight.js) are designed
    to accomodate (and even look) for this type of conversion.
    """
    def sub(match):
        block = match.group(0).rstrip('\n')
        block = re.sub(r'(?:(?<=\n)|(?<=\A)) {4}', '', block)
        block = html.escape(block)
        block = '<pre><code>{}</code></pre>'.format(block)
        hashed = hash_text(block, 'pre')
        hashes[hashed] = block
        return '\n' + hashed + '\n\n'
    return re_codeblock.sub(sub, text)

re_blockquote = re.compile(r"""
(?:(?<=\n)|(?<=\A))     # newline or start of string
(?:
    >[ ].*?\n*(?:\n\n|\Z)
)+
""", re.S | re.X)
def hash_blockquotes(text, hashes):
    """Hashes block quotes.

    Block quotes are defined to be lines that start with "> " (the
    space is not optional).

    All Markdown syntax in a blockquote is recursively converted,
    which allows (among other things) headers, codeblocks, and
    blockquotes to be used inside of blockquotes. The "> " is simply
    stripped from the front of any blockquote lines and the result is
    recursively converted.
    """
    def sub(match):
        block = match.group(0).strip()
        block = re.sub(r'(?:(?<=\n)|(?<=\A))> ', '', block)
        block = convert(block)[0]
        block = '<blockquote>\n{}\n</blockquote>'.format(block)
        hashed = hash_text(block, 'blockquote')
        hashes[hashed] = block
        return '\n' + hashed + '\n\n'
    return re_blockquote.sub(sub, text)

re_code = re.compile(r"""
(?<!\\)     # avoid escaped ticks
(`+)        # \1 is opening ticks (could be multiple ticks)
[ ]?        # leading space is optional
(.*?)       # \2 is code content
[ ]?        # closing space is optional
\1          # match closing ticks
""", re.S | re.X)
def hash_codes(text, hashes):
    """Hashes inline code tags.

    Code tags can begin with an arbitrary number of back-ticks, as long
    as the close contains the same number of back-ticks. This allows
    back-ticks to be used within the code tag.

    HTML entities (&, <, >, ", ') are automatically escaped inside the
    code tag.
    """
    def sub(match):
        code = '<code>{}</code>'.format(html.escape(match.group(2)))
        hashed = hash_text(code, 'code')
        hashes[hashed] = code
        return hashed
    return re_code.sub(sub, text)

re_inline_link = re.compile(r"""
(?<!\\)         # avoid escapes
(!?)            # \1 is whether or not this is an img
\[(.*?)\]       # \2 is <a> text or <img> alt text
\(              # captures link
    \s*
    (.*?)       # \3 is link
    (           # \4 is the title
        \s+
        (["'])  # \5 is quote type of title
        .+?     # title
        \5      # closing quote
    )?          # title is optional
    \s*
\)
""", re.X | re.S)
def hash_inline_links(text, hashes):
    """Hashes an <a> link or an <img> link.

    This function only converts inline link styles:

        [text here](path/to/resource "optional title")
        ![alt text here](path/to/resource "optional title")

    For reference style links, see hash_reference_links
    """
    def sub(match):
        is_img = match.group(1) != ''
        content = match.group(2)
        link = match.group(3)
        title = match.group(4)
        if title:
            title = ' title={0}'.format(title.strip())
        else:
            title = ''
        if is_img:
            result = '<img src="{0}" alt="{1}"{2}>'.format(
                    link, content, title)
        else:
            result = '<a href="{0}"{2}>{1}</a>'.format(link, content,
                    title)
        hashed = hash_text(result, 'link')
        hashes[hashed] = result
        return hashed
    return re_inline_link.sub(sub, text)

re_reference_link = re.compile(r"""
(?<!\\)     # avoid escapes
(!?)        # \1 is whether or not link is an <img>
\[(.*?)\]   # \2 is link text or img alt text
\[
    (.*?)   # \3 is reference id
\]
""", re.X | re.S)
def hash_reference_links(text, hashes, refs):
    """Hashes an <a> link or an <img> link.

    This function only converts reference link styles:

        [text here][ref id]
        ![alt text here][ref id]

    For inline style links, see hash_inline_links.

    Reference ids can be defined anywhere in the Markdown text.
    Reference ids can also be omitted, in which case te text in the
    first box is used as the reference id:

        [ref id][]

    This is known as an "implicit link" reference.
    """
    def sub(match):
        is_img = match.group(1) != ''
        content = match.group(2)
        ref = match.group(3).strip().lower()
        if not ref:
            ref = content.strip().lower()
        link, title = refs[ref]
        if title:
            title = ' title="{0}"'.format(title)
        if is_img:
            result = '<img src="{0}" alt="{1}"{2}>'.format(
                    link, content, title)
        else:
            result = '<a href="{0}"{2}>{1}</a>'.format(link, content,
                    title)
        hashed = hash_text(result, 'link')
        hashes[hashed] = result
        return hashed
    return re_reference_link.sub(sub, text)

re_tag = re.compile(r"""<[\w\s:/'"=]+?>""", re.S)
def hash_tags(text, hashes):
    """Hashes any non-block tags.

    Only the tags themselves are hashed -- the contains surrounded
    by tags are not touched. Indeed, there is no notion of "contained"
    text for non-block tags.

    Inline tags that are to be hashed are not white-listed, which
    allows users to define their own tags. These user-defined tags
    will also be preserved in their original form until the controller
    (see link.py) is applied to them.
    """
    def sub(match):
        hashed = hash_text(match.group(0), 'tag')
        hashes[hashed] = match.group(0)
        return hashed
    return re_tag.sub(sub, text)

re_hash = re.compile(r"""
(                   # \1 is hash type
    blockquote  |
    block       |
    code        |
    link        |
    tag         |
    list        |
    pre
)
-[\da-f]+-          # hash
\1                  # closing hash type
""", re.X)
re_pre_tag = re.compile(r"""
([ ]*)  # \1 is leading whitespace
<pre>
.*?
</pre>
""", re.S | re.X)
def unhash(text, hashes):
    """Unhashes all hashed entites in the hashes dictionary.

    The pattern for hashes is defined by re_hash. After everything is
    unhashed, <pre> blocks are "pulled out" of whatever indentation
    level in which they used to be (e.g. in a list).
    """
    def retrieve_match(match):
        return hashes[match.group(0)]
    while re_hash.search(text):
        text = re_hash.sub(retrieve_match, text)
    text = re_pre_tag.sub(lambda m: re.sub('^' + m.group(1), '', m.group(0), flags=re.M), text)
    return text

#################
# Substitutions #
#################

hr_re = re.compile(r"""
\n\n                    # leading blank line
(
    (?:\*[ ]?){3,}  |   # either * * * (spaces optional)
    (?:-[ ]?){3,}       # or - - - (spaces optional)
)
\n\n                    # trailing blank line
""", re.X | re.S)
def hr_sub(match):
    """Matches a horizontal rule."""
    return '\n\n<hr/>\n\n'

emphasis_re = re.compile(r"""
(?<!\\)             # avoid escapes
(\*{1,3}|_{1,3})    # \1 is the emphasis marker
(?!\s+)             # emphasis cannot contain leading whitespace
(.*?)               # \2 contents
\1                  # closing emphasis
""", re.S | re.X)
def emphasis_sub(match):
    """Substitutes <strong>, <em>, and <strong><em> tags."""
    level = len(match.group(1))
    content = match.group(2)
    if level == 3:
        return '<strong><em>{0}</em></strong>'.format(content)
    elif level == 2:
        return '<strong>{0}</strong>'.format(content)
    elif level == 1:
        return '<em>{0}</em>'.format(content)

auto_escape_re = re.compile(r"&(?!#[xX]?[0-9a-fA-F]+)")
def auto_escape_sub(match):
    """Escapes ampersands (&) in normal text."""
    return html.escape(match.group(0))

escape_re = re.compile(r"""
\\(         # escapes are preceded by a backslash
    \*  |
    `   |
    _   |
    \{  |
    \}  |
    \[  |
    \]  |
    \(  |
    \)  |
    #   |
    \+  |
    -   |
    \.  |
    !
)""", re.X)
def escapes_sub(match):
    """Substitutes escaped characters."""
    return match.group(1)

atx_header_re = re.compile(r"""
^(#{1,6})   # \1 is leading #s
\s*
(.*?)       # \2 is header title
\s*
#*$         # Trailing #s for aesthetics (doesn't have to match)
""", re.M)
def atx_header_sub(match):
    """Substitutes atx headers (headers defined using #'s)."""
    level = len(match.group(1))
    title = match.group(2)
    return '<h{0}>{1}</h{0}>'.format(level, title)

setext_header_re = re.compile(r"""
(?:(?<=\n)|(?<=\A))     # begin at newline
(.*?)                   # \1 is header title
\n
(=+|-+)                 # \2 is header underline style
(?=\n|\Z)               # must be followed by newline
""", re.X)
def setext_header_sub(match):
    """Substitutes setext headers (defined with underscores)."""
    title = match.group(1)
    level = 1 if '=' in match.group(2) else 2
    return '<h{0}>{1}</h{0}>'.format(level, title)

avoids = """
    (?:(?P<hash>blockquote|block|tag|pre|list)-[\da-f]+-(?P=hash))|<h(?P<level>[1-6])>.*?</h(?P=level)>|<hr/>
"""
paragraph_re = re.compile(r"""
(?:(?<=\n\n)|(?<=\A))   # begin at newline
(?!\n)                  # but don't include newlines in the paragraph
(?!%s)                  # avoid certain strings
(.+?)                   # \1 is paragraph contents
(?:(?=\n\n)|(?=\n*\Z))  # end with blank line or end of string
""" % avoids, re.S | re.X)
def paragraph_sub(match):
    """Captures paragraphs."""
    return '<p>{}</p>'.format(match.group(0))

###################
# Post-processing #
###################

slug_re = re.compile(r"""
<
    \s*
    ([0-6])     # \1 is the opening header level
    \s*
>
\s*
(.*?)           # \2 is the header title
\s*
<
    \s*/\s*
    \1          # closing header level
    \s*
>
""", re.X)
def slug_sub(match):
    """Assigns id-less headers a slug that is derived from their
    titles. Slugs are generated by lower-casing the titles, stripping
    all punctuation, and converting spaces to hyphens (-).
    """
    level = match.group(1)
    title = match.group(2)
    slug = title.lower()
    slug = slug.replace(' ', '-')
    slug = re.sub(r'<.+?>|[^\w-]', '', slug)
    return '<{0} id="{1}">{2}</{0}>'.format(level, slug, title)

if __name__ == '__main__':
    import sys
    with open(sys.argv[1], 'r') as f:
        print(convert(f.read())[0])
