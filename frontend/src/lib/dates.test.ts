import { describe, expect, it } from "vitest";

import { startOfToday } from "./dates";

describe("startOfToday", () => {
  it("시각을 버리고 자정으로 맞춰야 한다", () => {
    // Left in, the calendar compares its cells against this afternoon and
    // greys out today itself.
    const start = startOfToday(new Date(2026, 7, 6, 23, 59, 59));

    expect([start.getHours(), start.getMinutes(), start.getSeconds()]).toEqual([0, 0, 0]);
  });

  it("연·월·일은 그대로여야 한다", () => {
    const start = startOfToday(new Date(2026, 7, 6, 13, 30));

    expect([start.getFullYear(), start.getMonth(), start.getDate()]).toEqual([2026, 7, 6]);
  });

  it("전달한 날짜를 변경하지 않아야 한다", () => {
    const now = new Date(2026, 7, 6, 13, 30);

    startOfToday(now);

    expect(now.getHours()).toBe(13);
  });
});
