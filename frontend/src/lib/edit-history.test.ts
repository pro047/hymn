// No environment docblock on purpose: nothing here touches the DOM. See
// conti-order.test.ts for why the tag must not be spelled out in a comment.
import { describe, expect, it } from "vitest";

import { createEditHistory, HISTORY_LIMIT } from "./edit-history";

/** Stand-ins for a fabric document. The module never looks inside one, so a
 * short string says everything a real 12KB snapshot would. */
const EMPTY = '{"objects":[]}';
const ONE = '{"objects":[1]}';
const TWO = '{"objects":[1,2]}';
const THREE = '{"objects":[1,2,3]}';

describe("createEditHistory", () => {
  it("연 직후에는 되돌릴 것이 없어야 한다", () => {
    // Arrange
    const history = createEditHistory();

    // Act
    history.reset(EMPTY);

    // Assert
    expect(history.canUndo()).toBe(false);
    expect(history.depth()).toBe(1);
  });

  it("변경을 기록하면 되돌릴 수 있어야 한다", () => {
    // Arrange
    const history = createEditHistory();
    history.reset(EMPTY);

    // Act
    history.record(ONE);

    // Assert
    expect(history.canUndo()).toBe(true);
    expect(history.depth()).toBe(2);
  });

  it("되돌리면 직전 상태를 돌려줘야 한다", () => {
    // Arrange
    const history = createEditHistory();
    history.reset(EMPTY);
    history.record(ONE);
    history.record(TWO);

    // Act
    const restored = history.undo();

    // Assert — the state *before* the last change, not the last change itself.
    expect(restored).toBe(ONE);
    expect(history.depth()).toBe(2);
  });

  it("연속으로 되돌리면 한 단계씩 거슬러야 한다", () => {
    // Arrange
    const history = createEditHistory();
    history.reset(EMPTY);
    history.record(ONE);
    history.record(TWO);
    history.record(THREE);

    // Act & Assert
    expect(history.undo()).toBe(TWO);
    expect(history.undo()).toBe(ONE);
    expect(history.undo()).toBe(EMPTY);
  });

  it("연 상태까지 되돌리면 더는 되돌릴 수 없어야 한다", () => {
    // Arrange
    const history = createEditHistory();
    history.reset(EMPTY);
    history.record(ONE);

    // Act
    history.undo();

    // Assert
    expect(history.canUndo()).toBe(false);
    expect(history.undo()).toBeNull();
    expect(history.depth()).toBe(1);
  });

  it("기록이 없으면 되돌리기가 아무것도 돌려주지 않아야 한다", () => {
    // Arrange
    const history = createEditHistory();
    history.reset(EMPTY);

    // Act & Assert
    expect(history.undo()).toBeNull();
  });

  it("같은 상태를 연달아 기록하면 쌓이지 않아야 한다", () => {
    // Arrange — fabric fires several events for one gesture, and a re-render
    // can replay the last one.
    const history = createEditHistory();
    history.reset(EMPTY);

    // Act
    history.record(ONE);
    history.record(ONE);
    history.record(ONE);

    // Assert — otherwise one stroke would take three presses to undo.
    expect(history.depth()).toBe(2);
    expect(history.undo()).toBe(EMPTY);
  });

  it("떨어져 있으면 같은 상태라도 다시 기록해야 한다", () => {
    // Arrange
    const history = createEditHistory();
    history.reset(EMPTY);

    // Act — drawn, deleted, drawn again: the last state equals the first, but
    // the two presses in between really happened.
    history.record(ONE);
    history.record(EMPTY);
    history.record(ONE);

    // Assert
    expect(history.depth()).toBe(4);
  });

  it("상한을 넘으면 가장 오래된 것부터 버려야 한다", () => {
    // Arrange
    const history = createEditHistory(3);
    history.reset(EMPTY);

    // Act
    history.record(ONE);
    history.record(TWO);
    history.record(THREE);

    // Assert — depth is capped, and it is the opening state that fell off.
    expect(history.depth()).toBe(3);
    expect(history.undo()).toBe(TWO);
    expect(history.undo()).toBe(ONE);
    expect(history.canUndo()).toBe(false);
  });

  it("상한에 걸려도 최근 것은 남아 있어야 한다", () => {
    // Arrange
    const history = createEditHistory(2);
    history.reset(EMPTY);

    // Act
    history.record(ONE);
    history.record(TWO);
    history.record(THREE);

    // Assert — the newest change is always undoable, however small the cap.
    expect(history.depth()).toBe(2);
    expect(history.undo()).toBe(TWO);
  });

  it("되돌린 뒤에 새로 그리면 그 지점에서 이어져야 한다", () => {
    // Arrange
    const history = createEditHistory();
    history.reset(EMPTY);
    history.record(ONE);
    history.record(TWO);
    history.undo();

    // Act
    history.record(THREE);

    // Assert — the undone TWO is gone for good; there is no redo.
    expect(history.depth()).toBe(3);
    expect(history.undo()).toBe(ONE);
    expect(history.undo()).toBe(EMPTY);
  });

  it("다시 열면 이전 곡의 기록이 남아 있지 않아야 한다", () => {
    // Arrange — the same hook drives the next sheet the leader opens.
    const history = createEditHistory();
    history.reset(EMPTY);
    history.record(ONE);
    history.record(TWO);

    // Act
    history.reset(THREE);

    // Assert
    expect(history.canUndo()).toBe(false);
    expect(history.depth()).toBe(1);
    expect(history.undo()).toBeNull();
  });

  it("상한 기본값은 스무 단계여야 한다", () => {
    // Arrange — a snapshot measured at 10~50KB, so twenty of them stay well
    // under a megabyte. Pinned because the cap is what bounds the memory.
    expect(HISTORY_LIMIT).toBe(20);

    // Act
    const history = createEditHistory();
    history.reset(EMPTY);
    for (let i = 0; i < 30; i += 1) history.record(`{"objects":[${i}]}`);

    // Assert
    expect(history.depth()).toBe(HISTORY_LIMIT);
  });
});
