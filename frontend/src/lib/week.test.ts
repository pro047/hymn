import { describe, expect, it } from "vitest";

import { currentWeekStart } from "./week";

const iso = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate()
  ).padStart(2, "0")}`;

describe("currentWeekStart", () => {
  it("일요일이면 그날 자신이어야 한다", () => {
    // 2026-08-02 is a Sunday.
    expect(iso(currentWeekStart(new Date(2026, 7, 2)))).toBe("2026-08-02");
  });

  it("주중이면 그 주의 일요일로 내려가야 한다", () => {
    // Thursday 2026-08-06 belongs to the week opening 2026-08-02. Getting this
    // wrong by a day blocks the week the user is actually working on.
    expect(iso(currentWeekStart(new Date(2026, 7, 6)))).toBe("2026-08-02");
  });

  it("토요일이면 6일 전 일요일이어야 한다", () => {
    expect(iso(currentWeekStart(new Date(2026, 7, 8)))).toBe("2026-08-02");
  });

  it("월 경계를 넘어가도 맞아야 한다", () => {
    // Tuesday 2026-09-01 opens on Sunday 2026-08-30.
    expect(iso(currentWeekStart(new Date(2026, 8, 1)))).toBe("2026-08-30");
  });

  it("시각을 버리고 자정으로 맞춰야 한다", () => {
    // Otherwise the calendar compares against a mid-day timestamp and treats
    // this week's own Sunday as already past.
    const start = currentWeekStart(new Date(2026, 7, 6, 23, 59, 59));
    expect([start.getHours(), start.getMinutes(), start.getSeconds()]).toEqual([0, 0, 0]);
  });

  it("전달한 날짜를 변경하지 않아야 한다", () => {
    const today = new Date(2026, 7, 6);
    currentWeekStart(today);
    expect(iso(today)).toBe("2026-08-06");
  });
});
