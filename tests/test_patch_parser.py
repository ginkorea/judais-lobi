# tests/test_patch_parser.py — Tests for core/patch/parser.py

import pytest

from core.patch.parser import ParseError, parse_patch_text


class TestParseModifyBlock:
    def test_single_modify(self):
        text = """\
<<<< SEARCH src/main.py
old line
====
new line
>>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert len(patches) == 1
        assert patches[0].file_path == "src/main.py"
        assert patches[0].action == "modify"
        assert patches[0].search_block == "old line"
        assert patches[0].replace_block == "new line"

    def test_multiple_modify_blocks(self):
        text = """\
<<<< SEARCH a.py
line1
====
line2
>>>> REPLACE

Some commentary here.

<<<< SEARCH b.py
foo
====
bar
>>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert len(patches) == 2
        assert patches[0].file_path == "a.py"
        assert patches[1].file_path == "b.py"

    def test_empty_replace_block(self):
        text = """\
<<<< SEARCH x.py
delete this
====
>>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert len(patches) == 1
        assert patches[0].replace_block == ""

    def test_multiline_blocks(self):
        text = """\
<<<< SEARCH lib/utils.py
def old():
    return 1

====
def new():
    return 2

>>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert "def old():" in patches[0].search_block
        assert "def new():" in patches[0].replace_block

    def test_whitespace_preservation(self):
        text = """\
<<<< SEARCH f.py
    indented line
        more indented
====
    new indented
        still more
>>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert "    indented line" in patches[0].search_block
        assert "    new indented" in patches[0].replace_block

    def test_trailing_newline_preserved(self):
        text = "<<<< SEARCH f.py\nline\n====\nreplacement\n>>>> REPLACE"
        patches = parse_patch_text(text)
        # The content between delimiters is "line" (single line, no trailing newline
        # because the \n before ==== is the line separator in split)
        assert patches[0].search_block == "line"
        assert patches[0].replace_block == "replacement"

    def test_trailing_newline_in_content(self):
        text = "<<<< SEARCH f.py\nline\n\n====\nreplacement\n\n>>>> REPLACE"
        patches = parse_patch_text(text)
        # Extra blank line is preserved
        assert patches[0].search_block == "line\n"
        assert patches[0].replace_block == "replacement\n"


class TestParseCreateBlock:
    def test_create_block(self):
        text = """\
<<<< CREATE new_file.py
# New file
def hello():
    pass
>>>> CREATE
"""
        patches = parse_patch_text(text)
        assert len(patches) == 1
        assert patches[0].file_path == "new_file.py"
        assert patches[0].action == "create"
        assert "def hello():" in patches[0].replace_block

    def test_create_empty_content(self):
        text = """\
<<<< CREATE empty.py
>>>> CREATE
"""
        patches = parse_patch_text(text)
        assert len(patches) == 1
        assert patches[0].replace_block == ""


class TestParseDeleteBlock:
    def test_delete_single_line(self):
        text = "<<<< DELETE old_file.py >>>>"
        patches = parse_patch_text(text)
        assert len(patches) == 1
        assert patches[0].file_path == "old_file.py"
        assert patches[0].action == "delete"

    def test_delete_with_surrounding_text(self):
        text = """\
Remove the old config:

<<<< DELETE config/old.yml >>>>

Done.
"""
        patches = parse_patch_text(text)
        assert len(patches) == 1
        assert patches[0].file_path == "config/old.yml"


class TestParseMixedBlocks:
    def test_modify_create_delete(self):
        text = """\
First fix the main file:

<<<< SEARCH main.py
old code
====
new code
>>>> REPLACE

Create a new helper:

<<<< CREATE helpers.py
def help():
    pass
>>>> CREATE

Remove deprecated file:

<<<< DELETE legacy.py >>>>
"""
        patches = parse_patch_text(text)
        assert len(patches) == 3
        assert patches[0].action == "modify"
        assert patches[1].action == "create"
        assert patches[2].action == "delete"


class TestParseErrors:
    def test_unclosed_search_block(self):
        text = """\
<<<< SEARCH a.py
old code
"""
        with pytest.raises(ParseError, match="missing ==== separator"):
            parse_patch_text(text)

    def test_missing_replace_end(self):
        text = """\
<<<< SEARCH a.py
old
====
new
"""
        with pytest.raises(ParseError, match="missing >>>> REPLACE"):
            parse_patch_text(text)

    def test_unclosed_create_block(self):
        text = """\
<<<< CREATE a.py
content
"""
        with pytest.raises(ParseError, match="missing >>>> CREATE"):
            parse_patch_text(text)

    def test_absolute_path_rejected(self):
        text = "<<<< DELETE /etc/passwd >>>>"
        with pytest.raises(ParseError, match="Absolute path rejected"):
            parse_patch_text(text)

    def test_traversal_path_rejected(self):
        text = "<<<< DELETE ../../../etc/passwd >>>>"
        with pytest.raises(ParseError, match="Path traversal rejected"):
            parse_patch_text(text)

    def test_traversal_in_search_path(self):
        text = """\
<<<< SEARCH ../escape.py
old
====
new
>>>> REPLACE
"""
        with pytest.raises(ParseError, match="Path traversal rejected"):
            parse_patch_text(text)

    def test_empty_input(self):
        assert parse_patch_text("") == []
        assert parse_patch_text("   \n\n  ") == []

    def test_no_file_path_search(self):
        text = """\
<<<< SEARCH
old
====
new
>>>> REPLACE
"""
        # The regex won't match a SEARCH line with only whitespace after it,
        # so this won't even enter the SEARCH handler. But if there's trailing
        # space the path will be empty and validated.
        # Actually the regex r"<{4}\s+SEARCH\s+(.+)$" requires .+ so it needs
        # at least one non-whitespace char. Let's verify it passes through.
        patches = parse_patch_text(text)
        # The SEARCH line has nothing after "SEARCH ", so .+ doesn't match
        # and the line is skipped. The ==== and >>>> REPLACE are also skipped.
        assert len(patches) == 0


class TestParseEdgeCases:
    def test_commentary_between_blocks(self):
        text = """\
Here is my fix:

The problem was in the loop.

<<<< SEARCH x.py
old
====
new
>>>> REPLACE

That should fix it!
"""
        patches = parse_patch_text(text)
        assert len(patches) == 1

    def test_unicode_content(self):
        text = """\
<<<< SEARCH i18n.py
msg = "hello"
====
msg = "こんにちは"
>>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert "こんにちは" in patches[0].replace_block

    def test_delimiter_mid_line_not_treated_as_delimiter(self):
        text = """\
<<<< SEARCH code.py
x = "<<<< SEARCH fake"
====
x = "fixed"
>>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert len(patches) == 1
        assert '<<<< SEARCH fake' in patches[0].search_block

    def test_nested_delimiter_in_code_block(self):
        text = """\
<<<< SEARCH parser.py
if line.startswith("===="):
    pass
====
if line.startswith("===="):
    handle()
>>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert len(patches) == 1
        # The first ==== that appears at line start (the actual separator)
        # ends the search block. The ==== inside the if statement appears
        # after indentation so it's in the code.
        assert 'startswith("====")' in patches[0].search_block

    def test_file_path_with_spaces(self):
        text = """\
<<<< SEARCH my folder/my file.py
old
====
new
>>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert patches[0].file_path == "my folder/my file.py"

    def test_leading_whitespace_on_delimiter(self):
        text = """\
  <<<< SEARCH src.py
old
  ====
new
  >>>> REPLACE
"""
        patches = parse_patch_text(text)
        assert len(patches) == 1
