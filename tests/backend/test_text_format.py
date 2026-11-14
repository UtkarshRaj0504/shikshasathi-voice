"""
Unit tests for the answer formatting helpers.

Covers markdown normalisation for rendering and markdown stripping for speech,
including Hindi/Kannada text and the edge case of legitimate lone asterisks
(e.g. multiplication in "2 * 3") that must not be destroyed.
"""

from app.services.text_format import (
    normalize_answer_markdown,
    strip_markdown_for_speech,
)


# --------------------------------------------------------------------------- #
# normalize_answer_markdown
# --------------------------------------------------------------------------- #

def test_normalize_converts_star_bullets_to_dash_bullets():
    text = "* First point\n* Second point"
    assert normalize_answer_markdown(text) == "- First point\n- Second point"


def test_normalize_removes_heading_markers():
    text = "# Title\n## Section\n\nBody text."
    assert normalize_answer_markdown(text) == "Title\nSection\n\nBody text."


def test_normalize_removes_code_fences_but_keeps_content():
    text = "Here is an example:\n```python\nprint('hi')\n```"
    assert normalize_answer_markdown(text) == "Here is an example:\nprint('hi')"


def test_normalize_trims_trailing_spaces_on_each_line():
    text = "line one   \nline two\t"
    assert normalize_answer_markdown(text) == "line one\nline two"


def test_normalize_collapses_many_blank_lines():
    text = "para one\n\n\n\n\npara two"
    assert normalize_answer_markdown(text) == "para one\n\npara two"


def test_normalize_keeps_legitimate_lone_asterisks():
    # A line-leading "* " bullet is normalised, but an inline multiplication is not.
    assert normalize_answer_markdown("2 * 3 = 6") == "2 * 3 = 6"
    assert normalize_answer_markdown("- price is 5 * 4 rupees") == "- price is 5 * 4 rupees"


def test_normalize_empty_and_none():
    assert normalize_answer_markdown("") == ""
    assert normalize_answer_markdown(None) == ""


def test_normalize_preserves_plain_prose_and_indic_text():
    hindi = "प्रकाश संश्लेषण एक प्रक्रिया है।"
    kannada = "ದ್ಯುತಿಸಂಶ್ಲೇಷಣೆ ಒಂದು ಪ್ರಕ್ರಿಯೆ."
    assert normalize_answer_markdown(hindi) == hindi
    assert normalize_answer_markdown(kannada) == kannada


# --------------------------------------------------------------------------- #
# strip_markdown_for_speech
# --------------------------------------------------------------------------- #

def test_speech_removes_bold_and_italic_markers():
    assert strip_markdown_for_speech("**bold** and *italic* text") == "bold and italic text"


def test_speech_removes_underscore_emphasis():
    assert strip_markdown_for_speech("__strong__ and _emphasis_") == "strong and emphasis"


def test_speech_keeps_underscores_inside_words():
    assert strip_markdown_for_speech("use snake_case_names here") == "use snake_case_names here"


def test_speech_removes_heading_markers():
    assert strip_markdown_for_speech("## Photosynthesis\nIt converts light.") == (
        "Photosynthesis\nIt converts light."
    )


def test_speech_removes_backticks_keeping_content():
    assert strip_markdown_for_speech("call `embed_passage` now") == "call embed_passage now"


def test_speech_keeps_link_text_only():
    assert strip_markdown_for_speech("See [the docs](https://example.com/docs) for more.") == (
        "See the docs for more."
    )
    assert strip_markdown_for_speech("![a plant](plant.png)") == "a plant"


def test_speech_turns_bullets_into_sentences():
    text = "- Water\n- Sunlight\n- Carbon dioxide"
    assert strip_markdown_for_speech(text) == "Water.\nSunlight.\nCarbon dioxide."


def test_speech_does_not_double_punctuate_bullets():
    assert strip_markdown_for_speech("- Already done.\n- Really?") == "Already done.\nReally?"


def test_speech_strips_numbered_list_markers():
    text = "1. First step\n2. Second step"
    assert strip_markdown_for_speech(text) == "First step.\nSecond step."


def test_speech_preserves_lone_asterisks_in_math():
    # The literal multiplication must survive so TTS reads "2 times 3", not garbage.
    assert strip_markdown_for_speech("2 * 3 = 6") == "2 * 3 = 6"
    assert strip_markdown_for_speech("The area is 5 * 4 cm.") == "The area is 5 * 4 cm."


def test_speech_handles_hindi_emphasis():
    assert strip_markdown_for_speech("**प्रकाश संश्लेषण** क्या है?") == "प्रकाश संश्लेषण क्या है?"


def test_speech_handles_kannada_bullets():
    text = "- **ವಿಜ್ಞಾನ** ಎಂದರೇನು\n- ಇದು ಒಂದು ವಿಷಯ"
    assert strip_markdown_for_speech(text) == "ವಿಜ್ಞಾನ ಎಂದರೇನು.\nಇದು ಒಂದು ವಿಷಯ."


def test_speech_combined_markdown():
    text = "## Heading\n\n- **Bold** item\n- `code` item\n\nSee [docs](http://x)."
    assert strip_markdown_for_speech(text) == (
        "Heading\n\nBold item.\ncode item.\n\nSee docs."
    )


def test_speech_empty_and_none():
    assert strip_markdown_for_speech("") == ""
    assert strip_markdown_for_speech(None) == ""


def test_speech_plain_prose_unchanged():
    text = "Photosynthesis is how plants make food."
    assert strip_markdown_for_speech(text) == text
