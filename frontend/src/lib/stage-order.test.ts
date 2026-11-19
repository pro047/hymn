// No environment docblock: pure functions, no DOM. The tag is matched anywhere
// in the file, so it is not spelled out here either.
import { describe, expect, it } from "vitest";

import { orderScoresBy, reorderStage, toStageOrderPayload } from "./stage-order";

const WEEK = Object.freeze(["a", "b", "c", "d", "e", "f", "g"]);

describe("reorderStage", () => {
  // AC-13
  it("앞 5곡 안에서 끌어 놓으면 주차 전체 순서를 돌려주고 뒤 곡은 상대 순서를 지켜야 한다", () => {
    // Act
    const up = reorderStage(WEEK, 5, "e", "a");
    const down = reorderStage(WEEK, 5, "a", "c");

    // Assert
    expect(up).toEqual(["e", "a", "b", "c", "d", "f", "g"]);
    expect(down).toEqual(["b", "c", "a", "d", "e", "f", "g"]);
  });

  // AC-13
  it("곡이 5곡보다 적으면 있는 곡만으로 순서를 바꿔야 한다", () => {
    // Act
    const next = reorderStage(["a", "b", "c"], 3, "c", "a");

    // Assert
    expect(next).toEqual(["c", "a", "b"]);
  });

  // AC-13
  it("이웃한 두 곡을 바꾸면 그 둘만 자리를 바꿔야 한다", () => {
    // Act
    const next = reorderStage(WEEK, 5, "d", "e");

    // Assert
    expect(next).toEqual(["a", "b", "c", "e", "d", "f", "g"]);
  });

  // AC-14
  it("같은 자리에 놓으면 null 이어야 한다", () => {
    expect(reorderStage(WEEK, 5, "c", "c")).toBeNull();
  });

  // AC-14
  it("놓을 곳이 없으면 null 이어야 한다", () => {
    expect(reorderStage(WEEK, 5, "c", null)).toBeNull();
  });

  // AC-14
  it("앞 5곡 밖의 곡이 끼면 null 이어야 한다", () => {
    expect(reorderStage(WEEK, 5, "f", "a")).toBeNull();
    expect(reorderStage(WEEK, 5, "a", "f")).toBeNull();
  });

  // AC-14
  it("주차에 없는 id 면 null 이어야 한다", () => {
    expect(reorderStage(WEEK, 5, "zz", "a")).toBeNull();
    expect(reorderStage(WEEK, 5, "a", "zz")).toBeNull();
  });

  // AC-14
  it("입력 배열을 바꾸지 않고 새 배열을 돌려줘야 한다", () => {
    // Arrange — WEEK is frozen: a mutating implementation throws here.
    const before = [...WEEK];

    // Act
    const next = reorderStage(WEEK, 5, "b", "d");

    // Assert
    expect(next).toEqual(["a", "c", "d", "b", "e", "f", "g"]);
    expect(next).not.toBe(WEEK);
    expect([...WEEK]).toEqual(before);
  });
});

describe("toStageOrderPayload", () => {
  // AC-15
  it("score_id 만 실은 항목을 순서대로 만들어야 한다", () => {
    // Act
    const payload = toStageOrderPayload(["a", "b"]);

    // Assert — no starts_new_page key at all, so the server keeps each break
    expect(payload).toEqual([{ score_id: "a" }, { score_id: "b" }]);
    payload.forEach((item) => expect(Object.keys(item)).toEqual(["score_id"]));
  });

  // AC-15
  it("빈 목록이면 빈 배열이어야 한다", () => {
    expect(toStageOrderPayload([])).toEqual([]);
  });
});

describe("orderScoresBy", () => {
  const scores = Object.freeze([
    { id: "a", title: "가" },
    { id: "b", title: "나" },
    { id: "c", title: "다" },
  ]);

  // AC-25
  it("ids 가 순열이면 그 순서로 다시 놓아야 한다", () => {
    // Act
    const ordered = orderScoresBy(scores, ["c", "a", "b"]);

    // Assert — the same objects, moved
    expect(ordered.map((score) => score.id)).toEqual(["c", "a", "b"]);
    expect(ordered[0]).toBe(scores[2]);
  });

  // AC-25
  it("ids 가 null 이면 원래 순서여야 한다", () => {
    expect(orderScoresBy(scores, null).map((score) => score.id)).toEqual(["a", "b", "c"]);
  });

  // AC-25
  it("길이가 다르면 원래 순서여야 한다", () => {
    expect(orderScoresBy(scores, ["c", "a"]).map((score) => score.id)).toEqual(["a", "b", "c"]);
    expect(orderScoresBy(scores, ["c", "a", "b", "d"]).map((score) => score.id)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  // AC-25
  it("모르는 id 가 섞이면 원래 순서여야 한다", () => {
    expect(orderScoresBy(scores, ["c", "a", "zz"]).map((score) => score.id)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });

  // AC-25
  it("같은 id 가 두 번 나오면 원래 순서여야 한다", () => {
    expect(orderScoresBy(scores, ["c", "c", "a"]).map((score) => score.id)).toEqual([
      "a",
      "b",
      "c",
    ]);
  });
});
