/** @vitest-environment jsdom */

/**
 * Covers one seam: that DatePicker hands `disabled` on to the calendar.
 *
 * The upload dialog's own tests mock this component away, so nothing there can
 * see whether the restriction survives the last hop — and "the calendar was
 * never told about the restriction" is exactly the bug this prop was added to
 * fix. Radix's popover and react-day-picker are third-party and stubbed; what
 * is under test is the forwarding, not them.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import DatePicker from "./DatePicker";

vi.mock("./ui/popover", () => ({
  // Rendered inline: the real PopoverContent only mounts once opened, which
  // would keep the calendar out of the tree entirely.
  Popover: ({ children }) => <div>{children}</div>,
  PopoverTrigger: ({ children }) => <div>{children}</div>,
  PopoverContent: ({ children }) => <div>{children}</div>,
}));

vi.mock("./ui/calendar", () => ({
  Calendar: ({ disabled }) => (
    <span data-testid="calendar-disabled">
      {disabled?.before ? disabled.before.toISOString() : "제한없음"}
    </span>
  ),
}));

afterEach(cleanup);

describe("DatePicker", () => {
  it("disabled 를 달력에 그대로 넘겨야 한다", () => {
    const floor = new Date(2026, 7, 6);

    render(<DatePicker value={null} onChange={() => {}} disabled={{ before: floor }} />);

    expect(screen.getByTestId("calendar-disabled").textContent).toBe(floor.toISOString());
  });

  it("disabled 가 없으면 제한 없이 렌더해야 한다", () => {
    render(<DatePicker value={null} onChange={() => {}} />);

    expect(screen.getByTestId("calendar-disabled").textContent).toBe("제한없음");
  });
});
