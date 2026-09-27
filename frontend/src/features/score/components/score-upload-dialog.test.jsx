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

const placeNowBox = () => screen.getByLabelText("업로드 후 바로 주차에 배치");

describe("제출 게이트", () => {
  it("제목과 파일만 있으면 주차 없이도 제출할 수 있어야 한다", () => {
    renderDialog();

    fillTitleAndFile();

    // Uploading files the song in the library; no Sunday is involved.
    expect(submitButton().disabled).toBe(false);
  });

  it("바로 배치를 켜면 주차를 고르기 전까지 비활성이어야 한다", () => {
    renderDialog();

    fillTitleAndFile();
    fireEvent.click(placeNowBox());

    expect(submitButton().disabled).toBe(true);
  });

  it("바로 배치를 켜고 주차를 고르면 활성이어야 한다", () => {
    renderDialog();

    fillTitleAndFile();
    fireEvent.click(placeNowBox());
    fireEvent.click(screen.getByRole("button", { name: "주차 고르기" }));

    expect(submitButton().disabled).toBe(false);
  });

  it("바로 배치를 켜지 않으면 주차 선택기를 보여주지 않아야 한다", () => {
    renderDialog();

    expect(screen.queryByRole("button", { name: "주차 고르기" })).toBeNull();
  });
});

describe("제출 payload", () => {
  it("업로드에는 제목과 파일만 넘겨야 한다", async () => {
    const { onUploadSubmit } = renderDialog();

    fillTitleAndFile("주 은혜임을");
    fireEvent.click(submitButton());

    await vi.waitFor(() => expect(onUploadSubmit).toHaveBeenCalledTimes(1));
    const payload = onUploadSubmit.mock.calls[0][0];
    expect(payload.title).toBe("주 은혜임을");
    expect(payload.file.name).toBe("score.pdf");
    // The upload no longer knows about Sundays, and the church comes from the
    // caller's token; either key would look like it still did something.
    expect(Object.keys(payload).sort()).toEqual(["file", "title"]);
  });

  it("바로 배치를 켜고 주차를 고르지 않았으면 제출해도 호출되지 않아야 한다", () => {
    const { onUploadSubmit } = renderDialog();

    fillTitleAndFile();
    fireEvent.click(placeNowBox());
    fireEvent.submit(submitButton().closest("form"));

    // The button is disabled, but the form can still be submitted by other
    // means; handleSubmit has its own copy of the gate and must keep it.
    expect(onUploadSubmit).not.toHaveBeenCalled();
  });
});

describe("추가 방식 선택", () => {
  it("'보관함'과 'PC 업로드'를 둘 다 고를 수 있어야 한다", () => {
    renderDialog();

    expect(screen.getByRole("button", { name: "보관함" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "PC 업로드" })).toBeTruthy();
  });
});

describe("업로드 결과 처리", () => {
  it("바로 배치를 켜면 올린 곡을 고른 주차에 배치해야 한다", async () => {
    // Arrange
    const onApplySavedScore = vi.fn().mockResolvedValue({ ok: true });
    const { props } = renderDialog({
      onUploadSubmit: vi.fn().mockResolvedValue({ ok: true, songId: "song-9" }),
      onApplySavedScore,
    });

    // Act
    fillTitleAndFile();
    fireEvent.click(placeNowBox());
    fireEvent.click(screen.getByRole("button", { name: "주차 고르기" }));
    fireEvent.click(submitButton());

    // Assert — upload first, then the library's own placement
    await vi.waitFor(() =>
      expect(onApplySavedScore).toHaveBeenCalledWith({ songId: "song-9", weekOf: "2026-08-02" })
    );
    expect(props.onUploadSubmit.mock.invocationCallOrder[0]).toBeLessThan(
      onApplySavedScore.mock.invocationCallOrder[0]
    );
    expect(window.alert).toHaveBeenCalledWith("보관함에 올리고 주차에 배치했습니다.");
    expect(props.onClose).toHaveBeenCalled();
  });

  it("바로 배치를 끄면 배치를 부르지 않아야 한다", async () => {
    // Arrange
    const { props } = renderDialog({
      onUploadSubmit: vi.fn().mockResolvedValue({ ok: true, songId: "song-9" }),
    });

    // Act
    fillTitleAndFile();
    fireEvent.click(submitButton());

    // Assert
    await vi.waitFor(() => expect(window.alert).toHaveBeenCalledWith("보관함에 업로드되었습니다."));
    expect(props.onApplySavedScore).not.toHaveBeenCalled();
  });

  it("배치만 실패하면 보관함에는 올라갔다고 알리고 닫아야 한다", async () => {
    // Arrange — the song exists now, so keeping the form for a retry would only
    // hit the same-title 409
    const { props } = renderDialog({
      onUploadSubmit: vi.fn().mockResolvedValue({ ok: true, songId: "song-9" }),
      onApplySavedScore: vi.fn().mockResolvedValue({ ok: false, message: "네트워크 오류" }),
    });

    // Act
    fillTitleAndFile();
    fireEvent.click(placeNowBox());
    fireEvent.click(screen.getByRole("button", { name: "주차 고르기" }));
    fireEvent.click(submitButton());

    // Assert
    await vi.waitFor(() => expect(props.onClose).toHaveBeenCalled());
    expect(window.alert.mock.calls[0][0]).toContain("보관함에는 올렸지만");
    expect(window.alert.mock.calls[0][0]).toContain("네트워크 오류");
  });

  it("409 detail을 그대로 보여주고 다이얼로그를 닫지 않아야 한다", async () => {
    // Arrange — the message is server-authored; the dialog must not invent its
    // own, and must keep the form so the user can fix the title.
    const detail = "이미 보관함에 있는 곡입니다. 보관함에서 골라 배치해 주세요.";
    const { props } = renderDialog({
      onUploadSubmit: vi.fn().mockResolvedValue({ ok: false, message: detail }),
    });

    // Act
    fillTitleAndFile();
    fireEvent.click(submitButton());

    // Assert
    await vi.waitFor(() => expect(screen.getByRole("alert").textContent).toBe(detail));
    expect(props.onClose).not.toHaveBeenCalled();
    expect(props.onApplySavedScore).not.toHaveBeenCalled();
    // The form survives for a retry — closing would throw the input away.
    expect(screen.getByLabelText("악보 제목").value).toBe("은혜");
    expect(window.alert).not.toHaveBeenCalled();
  });
});

describe("주차 달력 제한", () => {
  it("오늘 이전 날짜를 비활성화하도록 전달해야 한다", () => {
    renderDialog();
    fireEvent.click(placeNowBox());

    const passed = screen.getByTestId("week-disabled").textContent;
    const now = new Date();
    const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    expect(passed).toBe(midnight.toISOString());
  });
});
