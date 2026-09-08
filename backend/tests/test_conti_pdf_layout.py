"""Pins the pure layout math and the PDF writing of services/conti_pdf.py
(DESIGN.md §9, criteria 1-12). No DB, no S3, no network.

Two things here are worth reading before changing anything:

- The numbers are written out (1754, 1240, 47, 812, 895) rather than recomputed
  from the constants. Recomputing would make the test agree with whatever the
  implementation does; the point is to fail when a millimetre or a rounding rule
  moves, so the pixel is the assertion.
- Determinism is not tested by "call it twice and hope" — time.gmtime is
  replaced with a counter that never repeats, so a render that let Pillow stamp
  its own CreationDate could not possibly produce the same bytes twice.
"""

import itertools
import re
import time
from io import BytesIO

import pytest
from PIL import Image, PdfImagePlugin

from app.services import conti_pdf
from app.services.conti_pdf import (
    SLOTS_PER_PAGE,
    chunk_pages,
    fit_within,
    mm_to_px,
    page_size_px,
    render_conti_pdf,
    slot_boxes,
)

PAGE_W, PAGE_H = 1754, 1240
MARGIN = 47
SLOT_W, SLOT_H = 812, 1146
LEFT_X, RIGHT_X = 47, 895

WHITE = (255, 255, 255)
RED = (220, 30, 30)
GREEN = (30, 175, 60)
BLUE = (40, 60, 220)
YELLOW = (230, 200, 40)
PURPLE = (140, 40, 170)

# A source image whose ratio is exactly the slot's, so fit_within lands on the
# slot corner and the slot centre is unambiguously that image's colour.
SLOT_RATIO_SIZE = (SLOT_W // 2, SLOT_H // 2)

JPEG_SOI = b"\xff\xd8\xff"
JPEG_EOI = b"\xff\xd9"


def _pdf_page_images(pdf: bytes) -> list[Image.Image]:
    """The pages of a Pillow-written PDF, in file order.

    Every RGB page is embedded as a raw JPEG stream (DCTDecode), and inside a
    JPEG every 0xFF in the entropy-coded data is byte-stuffed as FF 00 — so
    FF D9 only ever occurs as the end-of-image marker and scanning for the
    marker pair is unambiguous.
    """
    pages = []
    start = pdf.find(JPEG_SOI)
    while start != -1:
        end = pdf.find(JPEG_EOI, start)
        assert end != -1, "JPEG stream without an EOI marker"
        page = Image.open(BytesIO(pdf[start : end + 2]))
        page.load()
        pages.append(page)
        start = pdf.find(JPEG_SOI, end + 2)
    return pages


def _declared_page_count(pdf: bytes) -> int:
    """The /Count of the PDF's page tree — what a reader trusts, as opposed to
    how many image streams happen to be in the file."""
    match = re.search(rb"/Count (\d+)\n", pdf)
    assert match is not None, "no page tree /Count in the PDF"
    return int(match.group(1))


def _solid(color: tuple[int, int, int], size: tuple[int, int] = SLOT_RATIO_SIZE) -> Image.Image:
    return Image.new("RGB", size, color)


def _assert_color(page: Image.Image, xy: tuple[int, int], expected: tuple[int, int, int]) -> None:
    """JPEG at quality 90 keeps a flat region's centre within a couple of levels;
    16 is loose enough not to be flaky and far tighter than the distance between
    any two colours used here."""
    actual = page.convert("RGB").getpixel(xy)
    assert all(abs(a - e) <= 16 for a, e in zip(actual, expected, strict=True)), (
        f"at {xy}: got {actual}, expected ~{expected}"
    )


def _slot_center(slot: int) -> tuple[int, int]:
    x = (LEFT_X, RIGHT_X)[slot] + SLOT_W // 2
    return x, MARGIN + SLOT_H // 2


# --- criteria 1-3: the page and its two slots --------------------------------


def test_the_page_should_be_a4_landscape_at_150dpi():
    # Act / Assert — 297x210mm at 150dpi, rounded
    assert page_size_px() == (PAGE_W, PAGE_H)


def test_mm_to_px_should_round_to_the_nearest_pixel_at_the_given_dpi():
    # Assert — an inch is the dpi, and the two constants the layout depends on
    assert mm_to_px(25.4) == 150
    assert mm_to_px(8.0) == 47  # 47.24 margin
    assert mm_to_px(6.0) == 35  # 35.43 gutter
    assert mm_to_px(25.4, dpi=300) == 300


def test_changing_the_page_constant_should_move_every_derived_number(monkeypatch):
    """Requirement 4: A3 is meant to be one constant away. If page_size_px or
    slot_boxes ever hard-codes A4, this is the test that notices."""
    # Arrange — A3 landscape
    monkeypatch.setattr(conti_pdf, "PAGE_SIZE_MM", (420.0, 297.0))

    # Act
    width, height = page_size_px()
    left, right = slot_boxes()

    # Assert — 420/25.4*150 = 2480.3, 297/25.4*150 = 1753.9
    assert (width, height) == (2480, 1754)
    assert left == (47, 47, 1175, 1660)
    assert right == (2480 - 47 - 1175, 47, 1175, 1660)


def test_the_two_slots_should_be_symmetric_columns():
    # Act
    boxes = slot_boxes()

    # Assert — exact geometry, not "there are two of them"
    assert len(boxes) == SLOTS_PER_PAGE == 2
    assert boxes[0] == (LEFT_X, MARGIN, SLOT_W, SLOT_H)
    assert boxes[1] == (RIGHT_X, MARGIN, SLOT_W, SLOT_H)
    # left margin == right margin
    assert boxes[0][0] == PAGE_W - (boxes[1][0] + boxes[1][2])


def test_the_two_slots_should_not_overlap_and_should_stay_on_the_page():
    # Act
    (left_x, left_y, left_w, left_h), (right_x, right_y, right_w, right_h) = slot_boxes()

    # Assert
    assert left_x + left_w <= right_x  # 859 <= 895
    assert right_x + right_w <= PAGE_W
    assert left_y >= 0 and left_y + left_h <= PAGE_H
    assert right_y >= 0 and right_y + right_h <= PAGE_H


# --- criteria 4-7: fit_within ------------------------------------------------


def test_a_tall_score_should_letterbox_without_distortion():
    # Arrange — the production median shape (538px wide)
    box = slot_boxes()[0]

    # Act
    x, y, w, h = fit_within((538, 760), box)

    # Assert — ratio preserved to within a pixel, and the height fills the slot
    assert w <= SLOT_W and h <= SLOT_H
    assert abs(w - 538 / 760 * h) <= 1
    assert h == SLOT_H
    assert (x, y) == (LEFT_X + (SLOT_W - w) // 2, MARGIN)


def test_a_wide_score_should_letterbox_without_being_cropped():
    # Arrange
    box = slot_boxes()[0]

    # Act
    _, y, w, h = fit_within((1600, 400), box)

    # Assert — the width fills the slot this time, nothing is clipped
    assert w == SLOT_W
    assert h == 203  # round(400 * 812/1600)
    assert abs(w - 1600 / 400 * h) <= 1
    assert y == MARGIN + (SLOT_H - h) // 2


def test_a_score_smaller_than_the_slot_should_be_scaled_up():
    """Decision 2: the output is read on a tablet, so refusing to enlarge would
    draw a 538px score at 40% of the space the page allows."""
    # Act
    _, _, w, h = fit_within((200, 280), slot_boxes()[0])

    # Assert
    assert w == SLOT_W
    assert h == 1137  # round(280 * 812/200)


def test_fit_within_should_center_the_image_inside_the_slot():
    # Arrange
    box = slot_boxes()[1]
    box_x, box_y, box_w, box_h = box

    # Act
    x, y, w, h = fit_within((900, 500), box)

    # Assert
    assert x - box_x == (box_w - w) // 2
    assert y - box_y == (box_h - h) // 2


# --- criterion 8: chunk_pages ------------------------------------------------


@pytest.mark.parametrize(
    ("count", "expected"),
    [(5, [2, 2, 1]), (4, [2, 2]), (2, [2]), (1, [1]), (0, [])],
)
def test_chunk_pages_should_put_two_songs_on_a_page(count, expected):
    # Arrange
    items = list(range(count))

    # Act
    pages = chunk_pages(items)

    # Assert — sizes and contents, so a reordering is caught too
    assert [len(page) for page in pages] == expected
    assert [item for page in pages for item in page] == items


# --- criteria 9-12: render_conti_pdf -----------------------------------------


def test_the_render_should_be_a_pdf_file():
    # Act
    pdf = render_conti_pdf([_solid(RED)])

    # Assert
    assert pdf.startswith(b"%PDF")
    assert pdf.endswith(b"%%EOF")


def test_the_render_should_not_stamp_a_creation_or_modification_date():
    """Criterion 10. Pillow's default is time.gmtime(), which would make the
    bytes change every second — see the control test below."""
    # Act
    pdf = render_conti_pdf([_solid(RED), _solid(BLUE)])

    # Assert
    assert b"/CreationDate" not in pdf
    assert b"/ModDate" not in pdf


def test_a_pdf_saved_without_the_date_pins_should_stamp_a_creation_date():
    """Criterion 12, done without editing the source: this is the mutant. It
    proves /CreationDate is a byte sequence Pillow really emits, so the absence
    assertion above is not passing for want of anything to find."""
    # Arrange
    buffer = BytesIO()

    # Act — the same save call, minus creationDate=None/modDate=None
    Image.new("RGB", (40, 40), "white").save(buffer, "PDF")

    # Assert
    assert b"/CreationDate" in buffer.getvalue()
    assert b"/ModDate" in buffer.getvalue()


def test_two_renders_should_be_byte_identical_even_when_the_clock_moves(monkeypatch):
    """Criterion 11. gmtime returns a fresh timestamp on every call here, so two
    renders can only match if no clock reading reaches the file at all."""
    # Arrange — the real gmtime is captured first; calling the patched name
    # from inside the replacement would recurse forever.
    real_gmtime = time.gmtime
    ticks = itertools.count()
    monkeypatch.setattr(
        PdfImagePlugin.time, "gmtime", lambda *args: real_gmtime(next(ticks) * 86400)
    )
    images = [_solid(RED), _solid(GREEN), _solid(BLUE)]

    # Act
    first = render_conti_pdf(images)
    second = render_conti_pdf(images)

    # Assert
    assert first == second
    assert next(ticks) > 0, "gmtime was never called — the patch would prove nothing"


def test_every_page_should_be_one_full_page_canvas():
    # Act
    pdf = render_conti_pdf([_solid(RED), _solid(BLUE), _solid(GREEN)])

    # Assert — 2 pages, each the whole A4 landscape canvas
    assert _declared_page_count(pdf) == 2
    pages = _pdf_page_images(pdf)
    assert [page.size for page in pages] == [(PAGE_W, PAGE_H), (PAGE_W, PAGE_H)]


def test_songs_should_fill_the_slots_left_to_right_and_leave_the_tail_blank():
    """Criteria 6 and 18 at the pixel level: five songs make three pages, the
    order across slots is the input order, and the unused slot stays white
    rather than repeating the previous song."""
    # Arrange — one flat colour per song so a slot's centre names its song
    colors = [RED, GREEN, BLUE, YELLOW, PURPLE]

    # Act
    pdf = render_conti_pdf([_solid(color) for color in colors])
    pages = _pdf_page_images(pdf)

    # Assert
    assert _declared_page_count(pdf) == 3
    assert len(pages) == 3
    for index, color in enumerate(colors):
        page = pages[index // 2]
        _assert_color(page, _slot_center(index % 2), color)
    # the last page holds one song; its right slot is untouched canvas
    _assert_color(pages[2], _slot_center(1), WHITE)
    _assert_color(pages[2], (PAGE_W - 5, PAGE_H - 5), WHITE)


def test_a_small_score_should_reach_the_slot_edges_after_scaling():
    """Guards the resize step, not just fit_within's arithmetic: a render that
    computed the box but pasted the original size would leave white here."""
    # Arrange — a quarter of the slot, same aspect ratio
    tiny = _solid(RED, (SLOT_W // 4, SLOT_H // 4))

    # Act
    pages = _pdf_page_images(render_conti_pdf([tiny]))

    # Assert — the slot's far corners are the image, not the canvas
    page = pages[0]
    _assert_color(page, (LEFT_X + 3, MARGIN + 3), RED)
    _assert_color(page, (LEFT_X + SLOT_W - 4, MARGIN + SLOT_H - 4), RED)
    # and the margin outside it is still white
    _assert_color(page, (LEFT_X - 10, MARGIN + SLOT_H // 2), WHITE)


def test_rendering_no_images_should_raise_rather_than_index_error():
    """The route cannot reach this (ContiEmpty comes first), but this is a
    public pure function: an empty call must state its precondition instead
    of surfacing pages[0]'s IndexError."""
    # Act & Assert
    with pytest.raises(ValueError):
        render_conti_pdf([])


def test_chunk_pages_should_reject_a_breaks_list_of_the_wrong_length():
    """zip's default would stop at the shorter sequence and silently drop
    songs off the end of the conti — the kind of quiet failure this feature
    exists to avoid."""
    # Act & Assert
    with pytest.raises(ValueError):
        chunk_pages([1, 2, 3], [False, True])


def test_chunk_pages_should_cut_where_a_break_asks():
    # Act & Assert — a break on the first item is a no-op, it already starts one
    assert chunk_pages([1, 2, 3, 4, 5], [True, False, False, False, False]) == [[1, 2], [3, 4], [5]]
    assert chunk_pages([1, 2, 3, 4, 5], [False, True, False, False, False]) == [[1], [2, 3], [4, 5]]
    assert chunk_pages([1, 2, 3], [False, True, True]) == [[1], [2], [3]]
    # A break on an item that already starts a page changes nothing
    assert chunk_pages([1, 2, 3, 4], [False, False, True, False]) == [[1, 2], [3, 4]]
