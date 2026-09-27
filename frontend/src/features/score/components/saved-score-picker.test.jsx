/** @vitest-environment jsdom */

import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import SavedScorePicker from "./saved-score-picker";

const saved = (id, title, useCount, lastWeekOf = null) => ({
  song_id: id,
  title,
  download_url: `https://example.test/${id}.png`,
  file_url: null,
  use_count: useCount,
  last_week_of: lastWeekOf,
});

const SCORES = [
  saved("a", "은혜 아니면", 1, "2026-09-06"),
  saved("b", "주만 바라볼찌라", 5, "2026-08-02"),
  saved("c", "은혜로다", 5, "2026-09-20"),
];

function renderPicker(overrides = {}) {
  const onSelect = vi.fn();
  render(<SavedScorePicker scores={SCORES} selectedId="" onSelect={onSelect} {...overrides} />);
  return { onSelect };
}

const tileTitles = () =>
  screen
    .getAllByRole("button")
    .map((tile) => within(tile).getByTestId("saved-score-title").textContent);

describe("SavedScorePicker", () => {
  afterEach(() => cleanup());

  it("should list the most used first, the more recently used breaking a tie", () => {
    renderPicker();
    expect(tileTitles()).toEqual(["은혜로다", "주만 바라볼찌라", "은혜 아니면"]);
  });

  it("should show each score's sheet, not only its title", () => {
    renderPicker();
    expect(screen.getByRole("img", { name: "은혜로다" }).getAttribute("src")).toBe(
      "https://example.test/c.png"
    );
  });

  it("should narrow the grid to titles matching the search, ignoring spaces", () => {
    renderPicker();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "은혜아니" } });
    expect(tileTitles()).toEqual(["은혜 아니면"]);
  });

  it("should find a title by its initial consonants", () => {
    renderPicker();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "ㅈㅁㅂ" } });
    expect(tileTitles()).toEqual(["주만 바라볼찌라"]);
  });

  it("should hand the chosen score to onSelect", () => {
    const { onSelect } = renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /주만 바라볼찌라/ }));
    expect(onSelect).toHaveBeenCalledWith("b");
  });

  it("should mark only the selected tile as pressed", () => {
    renderPicker({ selectedId: "a" });
    const pressed = screen
      .getAllByRole("button")
      .filter((tile) => tile.getAttribute("aria-pressed") === "true");
    expect(
      pressed.map((tile) => within(tile).getByTestId("saved-score-title").textContent)
    ).toEqual(["은혜 아니면"]);
  });

  it("should say the library is empty instead of drawing an empty grid", () => {
    renderPicker({ scores: [] });
    expect(screen.getByText("보관함이 비어 있습니다.")).toBeTruthy();
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("should say nothing matched when the search finds nothing", () => {
    renderPicker();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "없는곡" } });
    expect(screen.getByText("검색 결과가 없습니다.")).toBeTruthy();
  });

  it("should offer to upload the searched title when nothing matched", () => {
    const onUploadNew = vi.fn();
    renderPicker({ onUploadNew });

    fireEvent.change(screen.getByRole("searchbox"), { target: { value: " 새 노래 " } });
    fireEvent.click(screen.getByRole("button", { name: "보관함에 새 악보 올리기" }));

    expect(onUploadNew).toHaveBeenCalledWith("새 노래");
  });

  it("should offer to upload when the library is empty", () => {
    const onUploadNew = vi.fn();
    renderPicker({ scores: [], onUploadNew });

    fireEvent.click(screen.getByRole("button", { name: "보관함에 새 악보 올리기" }));

    expect(onUploadNew).toHaveBeenCalledWith("");
  });

  it("should not offer an upload while the search still has matches", () => {
    renderPicker({ onUploadNew: vi.fn() });

    expect(screen.queryByRole("button", { name: "보관함에 새 악보 올리기" })).toBeNull();
  });
});
