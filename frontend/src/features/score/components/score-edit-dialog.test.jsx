/** @vitest-environment jsdom */

/**
 * Pins the edit dialog's submit gate and payload.
 *
 * Editing used to be a window.prompt that could only change the title, so the
 * thing worth fixing here is that the file is *optional*: leaving it empty must
 * still submit, and must hand the hook a null file rather than something that
 * would make it ask for an upload URL it does not need.
 */

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import ScoreEditDialog from "./score-edit-dialog";

const SCORE = {
  id: "score-1",
  title: "은혜",
  file_url: "https://example.com/old.jpg",
  download_url: "https://example.com/signed-old.jpg",
};

const IMAGE = () => new File(["x"], "rescan.png", { type: "image/png" });

function renderDialog(overrides = {}) {
  const onSubmit = vi.fn().mockResolvedValue({ ok: true });
  const onClose = vi.fn();
  render(
    <ScoreEditDialog
      open
      score={SCORE}
      onClose={onClose}
      onSubmit={onSubmit}
      loading={false}
      {...overrides}
    />
  );
  return { onSubmit, onClose };
}

const saveButton = () => screen.getByRole("button", { name: "저장" });

beforeEach(() => {
  // jsdom has no blob URL implementation; the preview calls it on every file pick.
  globalThis.URL.createObjectURL = vi.fn(() => "blob:preview");
  globalThis.URL.revokeObjectURL = vi.fn();
});

afterEach(cleanup);

it("제목만 바꾸면 파일 없이 제출해야 한다", async () => {
  // Arrange
  const { onSubmit } = renderDialog();

  // Act
  fireEvent.change(screen.getByLabelText("악보 제목"), { target: { value: "새 제목" } });
  fireEvent.click(saveButton());

  // Assert — a null file is what keeps the hook from requesting an upload URL.
  await vi.waitFor(() =>
    expect(onSubmit).toHaveBeenCalledWith({
      scoreId: "score-1",
      title: "새 제목",
      file: null,
    })
  );
});

it("파일을 고르면 제목과 파일을 함께 제출해야 한다", async () => {
  // Arrange
  const { onSubmit } = renderDialog();
  const image = IMAGE();

  // Act
  fireEvent.change(screen.getByLabelText("악보 이미지"), { target: { files: [image] } });
  fireEvent.click(saveButton());

  // Assert
  await vi.waitFor(() =>
    expect(onSubmit).toHaveBeenCalledWith({
      scoreId: "score-1",
      title: "은혜",
      file: image,
    })
  );
});

it("아무것도 바꾸지 않으면 저장할 수 없어야 한다", () => {
  // Arrange & Act
  renderDialog();

  // Assert — an unchanged submit would still PATCH and refetch for nothing.
  expect(saveButton().disabled).toBe(true);
});

it("제목을 비우면 저장할 수 없어야 한다", () => {
  // Arrange
  renderDialog();

  // Act
  fireEvent.change(screen.getByLabelText("악보 제목"), { target: { value: "   " } });

  // Assert — trimmed, so whitespace is not a title.
  expect(saveButton().disabled).toBe(true);
});

it("파일을 고르기 전에는 현재 악보를 보여줘야 한다", () => {
  // Arrange & Act
  renderDialog();

  // Assert — the signed URL, not the stored one: the bucket is not public.
  expect(screen.getByAltText("은혜").src).toBe(SCORE.download_url);
  expect(screen.getByText("현재 악보")).toBeTruthy();
});

it("서명된 주소가 없는 옛 악보는 저장된 주소로 보여줘야 한다", () => {
  // Arrange & Act — rows predating the s3 key scheme resolve to download_url=null.
  renderDialog({ score: { ...SCORE, download_url: null } });

  // Assert
  expect(screen.getByAltText("은혜").src).toBe(SCORE.file_url);
});

it("저장에 실패하면 다이얼로그를 닫지 않고 이유를 보여줘야 한다", async () => {
  // Arrange — the page's own alert renders in normal flow, behind this
  // dialog's fixed backdrop, so the reason has to appear inside the dialog.
  const { onClose } = renderDialog({
    onSubmit: vi.fn().mockResolvedValue({ ok: false, message: "S3 업로드에 실패했습니다." }),
  });

  // Act
  fireEvent.change(screen.getByLabelText("악보 제목"), { target: { value: "새 제목" } });
  fireEvent.click(saveButton());

  // Assert
  await vi.waitFor(() =>
    expect(screen.getByRole("alert").textContent).toBe("S3 업로드에 실패했습니다.")
  );
  expect(onClose).not.toHaveBeenCalled();
});

it("실패 이유가 없으면 기본 문구라도 보여줘야 한다", async () => {
  // Arrange
  renderDialog({ onSubmit: vi.fn().mockResolvedValue({ ok: false }) });

  // Act
  fireEvent.change(screen.getByLabelText("악보 제목"), { target: { value: "새 제목" } });
  fireEvent.click(saveButton());

  // Assert — a silent failure reads as a no-op and invites a second submit.
  await vi.waitFor(() =>
    expect(screen.getByRole("alert").textContent).toBe("악보 수정에 실패했습니다.")
  );
});

it("저장 중에는 취소와 닫기를 누를 수 없어야 한다", () => {
  // Arrange & Act — closing only unmounts the dialog; the upload and the PATCH
  // run on in the page's hook, so a live 취소 would replace the file anyway.
  renderDialog({ loading: true });

  // Assert
  expect(screen.getByRole("button", { name: "취소" }).disabled).toBe(true);
  expect(screen.getByRole("button", { name: "닫기" }).disabled).toBe(true);
});

it("현재 악보를 불러오지 못하면 깨진 이미지 대신 안내를 보여줘야 한다", () => {
  // Arrange — an expired presign (they last 15 minutes) or a legacy PDF row.
  renderDialog();

  // Act
  fireEvent.error(screen.getByAltText("은혜"));

  // Assert
  expect(screen.queryByAltText("은혜")).toBeNull();
  expect(screen.getByText(/미리 볼 수 없습니다/)).toBeTruthy();
});

it("미리보기가 실패해도 새 파일을 고르면 다시 보여줘야 한다", () => {
  // Arrange
  renderDialog();
  fireEvent.error(screen.getByAltText("은혜"));

  // Act — a local blob is a different image from the one that failed.
  fireEvent.change(screen.getByLabelText("악보 이미지"), { target: { files: [IMAGE()] } });

  // Assert
  expect(screen.getByAltText("은혜").src).toBe("blob:preview");
});
