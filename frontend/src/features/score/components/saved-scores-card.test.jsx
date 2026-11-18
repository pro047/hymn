/** @vitest-environment jsdom */

/**
 * Pins the library card's two entry points per song: the tile places it on a
 * week, the 수정 button beside it edits the song itself.
 *
 * The edit button is a sibling of the tile, never inside it. A button nested in
 * a button is invalid HTML, and its click would bubble into the tile and open
 * the placement dialog on top of the edit one.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import SavedScoresCard from "./saved-scores-card";

const SONGS = [
  {
    song_id: "song-1",
    title: "은혜",
    file_url: "https://files.example.com/a.png",
    download_url: "https://s3.example.com/a.png?sig=1",
    created_at: "2026-10-01T00:00:00Z",
    use_count: 2,
  },
  {
    song_id: "song-2",
    title: "주의 사랑",
    file_url: "https://files.example.com/b.png",
    download_url: null,
    created_at: "2026-10-02T00:00:00Z",
    use_count: 0,
  },
];

afterEach(cleanup);

function renderCard({ onEditRequest } = {}) {
  const onApplyRequest = vi.fn();
  render(
    <SavedScoresCard
      scores={SONGS}
      onApplyRequest={onApplyRequest}
      onQuickUpload={vi.fn()}
      onEditRequest={onEditRequest}
    />
  );
  return { onApplyRequest };
}

const tileOf = (title) => screen.getByAltText(title).closest("button");

// AC-301
it("onEditRequest 를 주면 곡마다 버튼 안이 아닌 곳에 '<제목> 수정' 버튼이 하나씩 있어야 한다", () => {
  // Arrange & Act
  renderCard({ onEditRequest: vi.fn() });

  // Assert
  for (const song of SONGS) {
    const editButtons = screen.getAllByRole("button", { name: `${song.title} 수정` });
    expect(editButtons).toHaveLength(1);
    expect(editButtons[0].parentElement.closest("button")).toBeNull();
    // Not the tile itself either: the tile is the placement entry point.
    expect(editButtons[0]).not.toBe(tileOf(song.title));
  }
  expect(screen.getAllByRole("button", { name: / 수정$/ })).toHaveLength(SONGS.length);
});

// AC-302
it("'<제목> 수정' 을 누르면 그 곡으로 onEditRequest 만 한 번 불러야 한다", () => {
  // Arrange
  const onEditRequest = vi.fn();
  const { onApplyRequest } = renderCard({ onEditRequest });

  // Act — the second song, so a handler bound to the first one would show
  fireEvent.click(screen.getByRole("button", { name: "주의 사랑 수정" }));

  // Assert
  expect(onEditRequest).toHaveBeenCalledTimes(1);
  expect(onEditRequest).toHaveBeenCalledWith(SONGS[1]);
  expect(onApplyRequest).not.toHaveBeenCalled();
});

// AC-303
it("타일을 누르면 그 곡으로 onApplyRequest 를 부르고 onEditRequest 는 부르지 않아야 한다", () => {
  // Arrange
  const onEditRequest = vi.fn();
  const { onApplyRequest } = renderCard({ onEditRequest });

  // Act
  fireEvent.click(tileOf("은혜"));

  // Assert
  expect(onApplyRequest).toHaveBeenCalledTimes(1);
  expect(onApplyRequest).toHaveBeenCalledWith(SONGS[0]);
  expect(onEditRequest).not.toHaveBeenCalled();
});

// AC-303
it("onEditRequest 없이 그리면 수정 버튼을 그리지 않아야 한다", () => {
  // Arrange & Act
  renderCard();

  // Assert — the tiles are still there, the edit buttons are not
  expect(tileOf("은혜")).not.toBeNull();
  expect(tileOf("주의 사랑")).not.toBeNull();
  expect(screen.queryAllByRole("button", { name: / 수정$/ })).toHaveLength(0);
});
