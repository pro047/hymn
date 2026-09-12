"""A week's edited sheet: saving one, and throwing one away.

The edit lives in three columns that must move together — `edited_file_uri`,
the flattened PNG conti and the PDF draw, `edit_doc`, the objects the editor
reopens, and `edit_source_uri`, the sheet those objects were placed against.
Setting one without the others produces a row nobody can work with: a picture
whose markings can never be taken off, a document that draws nothing, or
markings replayed over a sheet they were never drawn on. Every writer goes
through this module so the grouping is decided in one place rather than three
that have to agree.
"""

from typing import Any

from app.models import Score


def clear_edit(score: Score) -> None:
    """Drops this usage's edit, leaving the song's own file to show through.

    All three, always. conti reads coalesce(edited_file_uri, song file), so
    clearing only the picture would already restore the right sheet — and
    leave a document behind that the next edit would replay over a background
    it was never drawn on, still pointing at the sheet it replaced.
    """
    score.edited_file_uri = None
    score.edit_doc = None
    score.edit_source_uri = None


def save_edit(
    score: Score,
    *,
    edited_file_uri: str,
    edit_doc: dict[str, Any],
    source_file_uri: str | None,
) -> None:
    """Points this usage at a freshly flattened sheet and the objects behind it.

    Replaces rather than appends: the column holds the current sheet, and the
    superseded object stays in the bucket unreferenced, the same way
    replace_song_file leaves the file it replaced. That is what makes keeping
    a history (M3) a matter of recording keys rather than recovering them.

    The caller is responsible for having checked that the key belongs to this
    church — this module does not see the request the key arrived on.
    """
    score.edited_file_uri = edited_file_uri
    score.edit_doc = edit_doc
    # Recorded from the song as it is *now*, not taken from the request: the
    # editor is told which sheet to open and has no say in it, so asking the
    # client which one it used would let a wrong answer through with nothing
    # to check it against.
    score.edit_source_uri = source_file_uri
