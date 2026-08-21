/** @vitest-environment jsdom */

/**
 * Pins that 콘티 offers only actions that exist.
 *
 * 섞기 and 발행 sat here as <Button> elements with no onClick at all — they
 * rendered, took a click, and did nothing. Neither has a backend: reordering
 * would need SetItem.order_no rewritten on demand (it is only touched when
 * week_of changes) and publishing would need a status transition (status is
 * written 'draft' once, never changed, and ScoreResponse does not carry it).
 *
 * These tests fail if someone puts either back before the endpoint exists.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import StageCard from "./stage-card";

const SCORES = [
  { id: "s1", title: "은혜", week_of: "2026-08-23" },
  { id: "s2", title: "믿음", week_of: "2026-08-23" },
];

function renderCard(overrides = {}) {
  const onUpdate = vi.fn();
  const onDelete = vi.fn();
  render(
    <StageCard
      scores={SCORES}
      weekOf="2026-08-23"
      onUpdate={onUpdate}
      onDelete={onDelete}
      savedScoreIds={new Set()}
      pendingSaveScoreId={null}
      onToggleSave={null}
      {...overrides}
    />
  );
  return { onUpdate, onDelete };
}

afterEach(cleanup);

it("동작하지 않는 섞기·발행 버튼을 보여주지 않아야 한다", () => {
  // Arrange & Act
  renderCard();

  // Assert
  expect(screen.queryByRole("button", { name: "섞기" })).toBeNull();
  expect(screen.queryByRole("button", { name: "발행" })).toBeNull();
});

it("남은 버튼은 모두 눌렀을 때 실제로 무언가를 해야 한다", () => {
  // Arrange — the general rule the two removals were an instance of.
  const { onUpdate, onDelete } = renderCard();

  // Act — click every button the card renders.
  const buttons = screen.getAllByRole("button");
  buttons.forEach((button) => fireEvent.click(button));

  // Assert — 2 rows x (제목 + 수정 + 삭제); every click reached a handler.
  expect(buttons.length).toBe(6);
  expect(onUpdate.mock.calls.length + onDelete.mock.calls.length).toBe(buttons.length);
});

it("악보를 누르면 그 악보 객체를 통째로 넘겨야 한다", () => {
  // Arrange — the edit dialog needs title and download_url, not just the id.
  const { onUpdate } = renderCard();

  // Act
  fireEvent.click(screen.getByRole("button", { name: "은혜" }));

  // Assert
  expect(onUpdate).toHaveBeenCalledWith(SCORES[0]);
});

it("돌아오는 일요일 주차를 표시해야 한다", () => {
  // Arrange & Act
  renderCard();

  // Assert
  expect(screen.getByText(/2026-08-23/)).toBeTruthy();
});

it("악보가 없으면 빈 상태를 안내해야 한다", () => {
  // Arrange & Act
  renderCard({ scores: [] });

  // Assert
  expect(screen.getByText(/악보가 없습니다/)).toBeTruthy();
});
