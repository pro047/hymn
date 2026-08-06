/** @vitest-environment jsdom */

/**
 * Pins the upload dialog's submit gate and payload.
 *
 * This dialog had no tests, which is why "does the upload button work" could
 * only be answered by opening a browser. Removing the church-name field
 * touched both the gate and the payload, so both are fixed here.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import ScoreUploadDialog from "./score-upload-dialog";

// The real DatePicker is a Radix popover wrapped around react-day-picker.
// Driving that in jsdom exercises those libraries rather than this dialog, so
// it is replaced with the smallest thing that can hand a date back.
// The stub also renders whatever `disabled` it was handed, so a test can check
// the restriction actually reaches the calendar. The original bug was that no
// restriction was passed at all, and a mock that swallowed the prop would hide
// a return to exactly that.
vi.mock("../../../components/DatePicker", () => ({
  default: ({ onChange, disabled }) => (
    <>
      <button type="button" onClick={() => onChange(new Date(2026, 7, 2))}>
        주차 고르기
      </button>
      <span data-testid="week-disabled">
        {disabled?.before ? disabled.before.toISOString() : "제한없음"}
      </span>
    </>
  ),
}));

const PDF = () => new File(["x"], "score.pdf", { type: "application/pdf" });

function renderDialog(overrides = {}) {
  const onUploadSubmit = vi.fn().mockResolvedValue({ ok: true });
  const props = {
    open: true,
    onClose: vi.fn(),
    onUploadSubmit,
    onApplySavedScore: vi.fn(),
    savedScores: [],
    uploadLoading: false,
    applyLoading: false,
    ...overrides,
  };
  render(<ScoreUploadDialog {...props} />);
  return { onUploadSubmit, props };
}

const submitButton = () => screen.getByRole("button", { name: "업로드" });

function fillTitleAndFile(title = "은혜") {
  fireEvent.change(screen.getByLabelText("악보 제목"), { target: { value: title } });
  fireEvent.change(screen.getByLabelText("이미지 파일"), {
    target: { files: [PDF()] },
  });
}

beforeEach(() => {
  vi.spyOn(window, "alert").mockImplementation(() => {});
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("교회 이름 입력칸", () => {
  it("없어야 한다", () => {
    renderDialog();

    // The church now comes from the caller's token, so a field for it could
    // only ever be ignored — and the server no longer accepts one.
    expect(screen.queryByLabelText("교회 이름")).toBeNull();
  });
});

describe("제출 게이트", () => {
  it("제목과 파일만 있고 주차가 없으면 제출 버튼이 비활성이어야 한다", () => {
    renderDialog();

    fillTitleAndFile();

    expect(submitButton().disabled).toBe(true);
  });

  it("제목·파일·주차가 모두 있으면 제출 버튼이 활성이어야 한다", () => {
    renderDialog();

    fillTitleAndFile();
    fireEvent.click(screen.getByRole("button", { name: "주차 고르기" }));

    // The gate used to also require a church name. Dropping that field must
    // not have left the condition asking for something nothing can supply.
    expect(submitButton().disabled).toBe(false);
  });

  it("보관함 업로드면 주차 없이도 제출할 수 있어야 한다", () => {
    renderDialog({ saveToLibrary: true });

    fillTitleAndFile();

    expect(submitButton().disabled).toBe(false);
  });
});

describe("제출 payload", () => {
  it("교회명 없이 제목·주차·파일만 넘겨야 한다", async () => {
    const { onUploadSubmit } = renderDialog();

    fillTitleAndFile("주 은혜임을");
    fireEvent.click(screen.getByRole("button", { name: "주차 고르기" }));
    fireEvent.click(submitButton());

    await vi.waitFor(() => expect(onUploadSubmit).toHaveBeenCalledTimes(1));
    const payload = onUploadSubmit.mock.calls[0][0];
    expect(payload.title).toBe("주 은혜임을");
    expect(payload.weekOf).toBe("2026-08-02");
    expect(payload.file.name).toBe("score.pdf");
    // Sending it would be harmless but misleading: the server drops unknown
    // keys silently, so a stale field looks like it still does something.
    expect(payload).not.toHaveProperty("churchName");
  });

  it("주차를 고르지 않았으면 제출해도 호출되지 않아야 한다", () => {
    const { onUploadSubmit } = renderDialog();

    fillTitleAndFile();
    fireEvent.submit(submitButton().closest("form"));

    // The button is disabled, but the form can still be submitted by other
    // means; handleSubmit has its own copy of the gate and must keep it.
    expect(onUploadSubmit).not.toHaveBeenCalled();
  });
});

describe("추가 방식 선택", () => {
  it("보관함 플래그가 꺼져 있으면 'PC 업로드'가 유일한 선택지여야 한다", () => {
    renderDialog();

    // And "pc" is already the initial mode, so clicking it changes nothing —
    // the button looks unresponsive because there is nothing to switch to.
    expect(screen.queryByRole("button", { name: "보관함" })).toBeNull();
    expect(screen.getByRole("button", { name: "PC 업로드" })).toBeTruthy();
  });
});

describe("주차 달력 제한", () => {
  it("오늘 이전 날짜를 비활성화하도록 전달해야 한다", () => {
    renderDialog();

    const passed = screen.getByTestId("week-disabled").textContent;
    const now = new Date();
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    expect(passed).toBe(midnight.toISOString());
  });
});
