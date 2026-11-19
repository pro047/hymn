/** @vitest-environment jsdom */

/**
 * Pins the library card's two entry points per song: the tile places it on a
 * week, the ⋮ menu beside it opens 수정, which edits the song itself.
 *
 * The menu button is a sibling of the tile, never inside it. A button nested in
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

function renderCard({ onEditRequest, onDeleteRequest } = {}) {
  const onApplyRequest = vi.fn();
  render(
    <SavedScoresCard
      scores={SONGS}
      onApplyRequest={onApplyRequest}
      onQuickUpload={vi.fn()}
      onEditRequest={onEditRequest}
      onDeleteRequest={onDeleteRequest}
    />
  );
  return { onApplyRequest };
}

const tileOf = (title) => screen.getByAltText(title).closest("button");
const openMenu = (title) => fireEvent.click(screen.getByRole("button", { name: `${title} 메뉴` }));

// AC-301
it("onEditRequest 를 주면 곡마다 버튼 안이 아닌 곳에 '<제목> 메뉴' 버튼이 하나씩 있어야 한다", () => {
  // Arrange & Act
  renderCard({ onEditRequest: vi.fn() });

  // Assert
  for (const song of SONGS) {
    const menuButtons = screen.getAllByRole("button", { name: `${song.title} 메뉴` });
    expect(menuButtons).toHaveLength(1);
    expect(menuButtons[0].parentElement.closest("button")).toBeNull();
    // Not the tile itself either: the tile is the placement entry point.
    expect(menuButtons[0]).not.toBe(tileOf(song.title));
  }
  // Closed until asked for: no 수정 item is on screen yet.
  expect(screen.queryAllByRole("button", { name: / 수정$/ })).toHaveLength(0);
});

it("'<제목> 메뉴' 를 열면 그 곡의 수정 항목 하나만 보여야 하고 onApplyRequest 는 부르지 않아야 한다", () => {
  // Arrange
  const { onApplyRequest } = renderCard({ onEditRequest: vi.fn() });

  // Act
  openMenu("주의 사랑");

  // Assert
  expect(screen.getAllByRole("button", { name: / 수정$/ })).toHaveLength(1);
  expect(screen.getByRole("button", { name: "주의 사랑 수정" })).not.toBeNull();
  expect(onApplyRequest).not.toHaveBeenCalled();
});

// AC-302
it("메뉴의 수정을 누르면 그 곡으로 onEditRequest 만 한 번 부르고 메뉴를 닫아야 한다", () => {
  // Arrange
  const onEditRequest = vi.fn();
  const { onApplyRequest } = renderCard({ onEditRequest });
  // The second song, so a handler bound to the first one would show
  openMenu("주의 사랑");

  // Act
  fireEvent.click(screen.getByRole("button", { name: "주의 사랑 수정" }));

  // Assert
  expect(onEditRequest).toHaveBeenCalledTimes(1);
  expect(onEditRequest).toHaveBeenCalledWith(SONGS[1]);
  expect(onApplyRequest).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "주의 사랑 수정" })).toBeNull();
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
it("onEditRequest 없이 그리면 메뉴 버튼을 그리지 않아야 한다", () => {
  // Arrange & Act
  renderCard();

  // Assert — the tiles are still there, the menus are not
  expect(tileOf("은혜")).not.toBeNull();
  expect(tileOf("주의 사랑")).not.toBeNull();
  expect(screen.queryAllByRole("button", { name: / 메뉴$/ })).toHaveLength(0);
  expect(screen.queryAllByRole("button", { name: / 수정$/ })).toHaveLength(0);
});

// AC-16
it("onDeleteRequest 를 주고 메뉴를 열면 수정 다음에 그 곡의 삭제 항목이 하나 있어야 한다", () => {
  // Arrange
  renderCard({ onEditRequest: vi.fn(), onDeleteRequest: vi.fn() });

  // Act
  openMenu("주의 사랑");

  // Assert
  const deleteItems = screen.getAllByRole("button", { name: / 삭제$/ });
  expect(deleteItems).toHaveLength(1);
  const deleteItem = screen.getByRole("button", { name: "주의 사랑 삭제" });
  expect(deleteItem.textContent).toBe("삭제");
  expect(deleteItem.getAttribute("type")).toBe("button");
  const editItem = screen.getByRole("button", { name: "주의 사랑 수정" });
  // DOM order: 수정 first, then 삭제.
  expect(
    editItem.compareDocumentPosition(deleteItem) & Node.DOCUMENT_POSITION_FOLLOWING
  ).toBeTruthy();
});

// AC-16
it("메뉴의 삭제를 누르면 그 곡으로 onDeleteRequest 만 한 번 부르고 메뉴를 닫아야 한다", () => {
  // Arrange
  const onEditRequest = vi.fn();
  const onDeleteRequest = vi.fn();
  const { onApplyRequest } = renderCard({ onEditRequest, onDeleteRequest });
  // The second song, so a handler bound to the first one would show
  openMenu("주의 사랑");

  // Act
  fireEvent.click(screen.getByRole("button", { name: "주의 사랑 삭제" }));

  // Assert
  expect(onDeleteRequest).toHaveBeenCalledTimes(1);
  expect(onDeleteRequest).toHaveBeenCalledWith(SONGS[1]);
  expect(onApplyRequest).not.toHaveBeenCalled();
  expect(onEditRequest).not.toHaveBeenCalled();
  expect(screen.queryByRole("button", { name: "주의 사랑 삭제" })).toBeNull();
  expect(screen.queryByRole("button", { name: "주의 사랑 수정" })).toBeNull();
});

// AC-17
it("onDeleteRequest 없이 그리면 메뉴를 열어도 삭제 항목이 없고 수정만 있어야 한다", () => {
  // Arrange
  renderCard({ onEditRequest: vi.fn() });

  // Act
  openMenu("은혜");

  // Assert
  expect(screen.queryAllByRole("button", { name: / 삭제$/ })).toHaveLength(0);
  expect(screen.getAllByRole("button", { name: / 수정$/ })).toHaveLength(1);
});

// AC-17
it("onDeleteRequest 만 주면 메뉴가 있고 그 안에 삭제만 있어야 한다", () => {
  // Arrange
  const onDeleteRequest = vi.fn();
  renderCard({ onDeleteRequest });

  // Act
  openMenu("은혜");

  // Assert
  expect(screen.getAllByRole("button", { name: / 메뉴$/ })).toHaveLength(SONGS.length);
  expect(screen.queryAllByRole("button", { name: / 수정$/ })).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", { name: "은혜 삭제" }));
  expect(onDeleteRequest).toHaveBeenCalledWith(SONGS[0]);
});

// AC-17
it("onEditRequest·onDeleteRequest 둘 다 없으면 메뉴 버튼도 삭제 항목도 없어야 한다", () => {
  // Arrange & Act
  renderCard();

  // Assert
  expect(screen.queryAllByRole("button", { name: / 메뉴$/ })).toHaveLength(0);
  expect(screen.queryAllByRole("button", { name: / 삭제$/ })).toHaveLength(0);
});
