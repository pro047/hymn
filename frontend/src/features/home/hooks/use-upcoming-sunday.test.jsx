/** @vitest-environment jsdom */

import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useUpcomingSunday } from "./use-upcoming-sunday";

// Weeks start on Monday, so Sunday is the last day of its own week and the
// value only moves at Monday 00:00. 2026-09-27 is a Sunday.
const SUNDAY_2359 = new Date(2026, 8, 27, 23, 59);
const MINUTE = 60 * 1000;
const HOUR = 60 * MINUTE;

function setVisibility(state) {
  Object.defineProperty(document, "visibilityState", { configurable: true, get: () => state });
  document.dispatchEvent(new Event("visibilitychange"));
}

describe("useUpcomingSunday", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    delete document.visibilityState;
  });

  it("should move to the next Sunday when Monday midnight passes with the page open", () => {
    vi.setSystemTime(SUNDAY_2359);
    const { result } = renderHook(() => useUpcomingSunday());
    expect(result.current).toBe("2026-09-27");

    act(() => {
      vi.advanceTimersByTime(2 * MINUTE);
    });

    expect(result.current).toBe("2026-10-04");
  });

  it("should keep moving week after week", () => {
    vi.setSystemTime(SUNDAY_2359);
    const { result } = renderHook(() => useUpcomingSunday());

    act(() => {
      vi.advanceTimersByTime(2 * MINUTE + 7 * 24 * HOUR);
    });

    expect(result.current).toBe("2026-10-11");
  });

  it("should catch up when the page becomes visible after the timer missed midnight", () => {
    vi.setSystemTime(SUNDAY_2359);
    const { result } = renderHook(() => useUpcomingSunday());

    // A sleeping device: the clock moves, the timer does not fire.
    vi.setSystemTime(new Date(2026, 8, 28, 9, 0));
    act(() => {
      setVisibility("visible");
    });

    expect(result.current).toBe("2026-10-04");
  });

  it("should not change within the same week", () => {
    vi.setSystemTime(new Date(2026, 8, 23, 10, 0)); // Wednesday
    const { result } = renderHook(() => useUpcomingSunday());

    act(() => {
      vi.advanceTimersByTime(12 * HOUR);
      setVisibility("visible");
    });

    expect(result.current).toBe("2026-09-27");
  });

  it("should stop listening once unmounted", () => {
    vi.setSystemTime(SUNDAY_2359);
    const { unmount } = renderHook(() => useUpcomingSunday());
    unmount();

    expect(vi.getTimerCount()).toBe(0);
  });
});
