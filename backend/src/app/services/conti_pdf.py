"""Pure layout math and PIL composition/saving for the weekly conti PDF.

No DB, no S3, no clock: render_conti_pdf must return the same bytes for the
same images every time it is called, which is why the PDF Info fields below
are all pinned to None rather than left at Pillow's defaults (PdfImagePlugin
stamps time.gmtime() into CreationDate/ModDate otherwise).
"""

from collections.abc import Sequence
from io import BytesIO

from PIL import Image  # type: ignore[import-not-found]

PAGE_SIZE_MM: tuple[float, float] = (297.0, 210.0)  # A4 landscape
PAGE_DPI: int = 150
PAGE_MARGIN_MM: float = 8.0
SLOT_GUTTER_MM: float = 6.0
SLOTS_PER_PAGE: int = 2
JPEG_QUALITY: int = 90


def mm_to_px(mm: float, dpi: int = PAGE_DPI) -> int:
    return round(mm / 25.4 * dpi)


def page_size_px(dpi: int = PAGE_DPI) -> tuple[int, int]:
    width_mm, height_mm = PAGE_SIZE_MM
    return mm_to_px(width_mm, dpi), mm_to_px(height_mm, dpi)


def slot_boxes(dpi: int = PAGE_DPI) -> list[tuple[int, int, int, int]]:
    """The two song slots on one page, left and right.

    The right slot's x is measured from the page's right edge inward by the
    same margin as the left slot, not by adding gutter to the left slot's
    width — that is what keeps the left/right margins symmetric at the cost
    of the effective gutter being a pixel or two wider than SLOT_GUTTER_MM.
    """
    page_w, page_h = page_size_px(dpi)
    margin = mm_to_px(PAGE_MARGIN_MM, dpi)
    gutter = mm_to_px(SLOT_GUTTER_MM, dpi)
    slot_h = page_h - 2 * margin
    slot_w = (page_w - 2 * margin - gutter) // SLOTS_PER_PAGE
    left_x = margin
    right_x = page_w - margin - slot_w
    return [(left_x, margin, slot_w, slot_h), (right_x, margin, slot_w, slot_h)]


def fit_within(src: tuple[int, int], box: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """Scale src to fit inside box keeping aspect ratio, centered (letterbox)."""
    src_w, src_h = src
    box_x, box_y, box_w, box_h = box
    scale = min(box_w / src_w, box_h / src_h)
    w = round(src_w * scale)
    h = round(src_h * scale)
    x = box_x + (box_w - w) // 2
    y = box_y + (box_h - h) // 2
    return x, y, w, h


def chunk_pages[T](items: Sequence[T], per_page: int = SLOTS_PER_PAGE) -> list[list[T]]:
    return [list(items[i : i + per_page]) for i in range(0, len(items), per_page)]


def render_conti_pdf(images: Sequence[Image.Image]) -> bytes:
    """Images, in placement order, to PDF bytes.

    strict=False on the zip below: the last page can hold one image against
    two slot boxes, and that is not a caller error.
    """
    if not images:
        # The route cannot reach this (list_week_entries raises ContiEmpty on
        # an empty week), but this is a public pure function: state the
        # precondition rather than let pages[0] raise an opaque IndexError.
        raise ValueError("render_conti_pdf needs at least one image")

    page_w, page_h = page_size_px()
    boxes = slot_boxes()
    pages: list[Image.Image] = []
    for page_images in chunk_pages(images, SLOTS_PER_PAGE):
        canvas = Image.new("RGB", (page_w, page_h), "white")
        for image, box in zip(page_images, boxes, strict=False):
            x, y, w, h = fit_within((image.width, image.height), box)
            canvas.paste(image.resize((w, h), Image.Resampling.LANCZOS), (x, y))
        pages.append(canvas)

    buffer = BytesIO()
    pages[0].save(
        buffer,
        "PDF",
        save_all=True,
        append_images=pages[1:],
        dpi=(PAGE_DPI, PAGE_DPI),
        quality=JPEG_QUALITY,
        # None, not omitted: Pillow's default is time.gmtime(), which would
        # make the output non-deterministic (see module docstring).
        creationDate=None,
        modDate=None,
        title=None,
        author=None,
        subject=None,
        keywords=None,
        creator=None,
        producer=None,
    )
    return buffer.getvalue()
