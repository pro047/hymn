/** @vitest-environment jsdom */

/**
 * Pins that the hero shows one real number, not three tiles of decoration.
 *
 * "상태: Draft" and "버전: v1" were literal strings in the JSX. Score.status
 * never reaches the client (ScoreResponse omits it) and nothing in the codebase
 * versions a week, so neither tile could ever have shown anything else.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import HeroSection from "./hero-section";

afterEach(cleanup);

it("총 곡 수를 실제 값으로 보여줘야 한다", () => {
  // Arrange & Act
  render(<HeroSection totalSongs={150} onUpload={vi.fn()} />);

  // Assert
  expect(screen.getByText("150")).toBeTruthy();
  expect(screen.getByText("총 곡 수")).toBeTruthy();
});

it("바뀔 수 없는 상태·버전 타일을 보여주지 않아야 한다", () => {
  // Arrange & Act
  render(<HeroSection totalSongs={0} onUpload={vi.fn()} />);

  // Assert
  expect(screen.queryByText("Draft")).toBeNull();
  expect(screen.queryByText("v1")).toBeNull();
  expect(screen.queryByText("상태")).toBeNull();
  expect(screen.queryByText("버전")).toBeNull();
});

it("업로드 버튼은 핸들러를 불러야 한다", () => {
  // Arrange
  const onUpload = vi.fn();
  render(<HeroSection totalSongs={0} onUpload={onUpload} />);

  // Act
  fireEvent.click(screen.getByRole("button", { name: "악보 업로드" }));

  // Assert
  expect(onUpload).toHaveBeenCalledTimes(1);
});
