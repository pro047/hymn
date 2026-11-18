/** @vitest-environment jsdom */

/**
 * Pins the wire from the home page to the score hook for a drag on 콘티.
 *
 * The card knows only the songs it was handed and the hook knows only what
 * it is asked to save; what joins them is the page — which week the card is
 * showing, and that the order sent names that week's songs and no other.
 * The hook and the week are replaced so the page is the only thing under test.
 */

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import { useScores } from "../features/score/hooks/use-scores";
import HomePage from "./home-page";

const SUNDAY = "2026-11-22";
const NEXT_SUNDAY = "2026-11-29";

const dnd = vi.hoisted(() => ({ props: null }));

/** Kept apart from the render so the render itself writes nothing outside. */
function remember(props) {
  dnd.props = props;
}

vi.mock("@dnd-kit/core", async (importOriginal) => {
  const actual = await importOriginal();
  function CapturingDndContext(props) {
    remember(props);
    return <actual.DndContext {...props} />;
  }
  return { ...actual, DndContext: CapturingDndContext };
});

vi.mock("../features/home/hooks/use-upcoming-sunday", () => ({
  useUpcomingSunday: () => SUNDAY,
}));

vi.mock("../features/score/hooks/use-scores", () => ({ useScores: vi.fn() }));

// Another week's song sits between this week's, so a page that forgot to
// filter, or filtered after ordering, would carry it into the request.
const SCORES = [
  { id: "s1", song_id: "g1", title: "곡1", week_of: SUNDAY },
  { id: "s2", song_id: "g2", title: "곡2", week_of: SUNDAY },
  { id: "x1", song_id: "g9", title: "다음주곡", week_of: NEXT_SUNDAY },
  { id: "s3", song_id: "g3", title: "곡3", week_of: SUNDAY },
  { id: "s4", song_id: "g4", title: "곡4", week_of: SUNDAY },
  { id: "s5", song_id: "g5", title: "곡5", week_of: SUNDAY },
  { id: "s6", song_id: "g6", title: "곡6", week_of: SUNDAY },
];

// Titled unlike every week song, so a "<title> 수정" button found on screen
// can only be the library card's.
const LIBRARY_SONG = {
  song_id: "lib-1",
  title: "보관함곡",
  file_url: "https://files.example.com/lib.png",
  download_url: "https://s3.example.com/lib.png?sig=1",
  created_at: "2026-10-01T00:00:00Z",
  use_count: 3,
};

let reorderWeek;
let updateSong;
let hookValue;

beforeEach(() => {
  dnd.props = null;
  reorderWeek = vi.fn(async () => ({ ok: true, saved: true }));
  updateSong = vi.fn(async () => ({ ok: true }));
  hookValue = {
    scores: SCORES,
    totalSongs: 7,
    librarySongs: [LIBRARY_SONG],
    error: "",
    isUploading: false,
    isUpdating: false,
    isPlacingSong: false,
    isReordering: false,
    uploadSong: vi.fn(),
    updateScore: vi.fn(),
    deleteScore: vi.fn(),
    placeSongOnWeek: vi.fn(),
    reorderWeek,
    updateSong,
  };
  useScores.mockReturnValue(hookValue);
});

afterEach(cleanup);

function renderHome(canManage) {
  return render(
    <MemoryRouter>
      <HomePage canManage={canManage} />
    </MemoryRouter>
  );
}

// AC-24
it("인도자가 홈 콘티에서 곡을 끌어 놓으면 그 주차의 새 순서로 reorderWeek 를 한 번 불러야 한다", async () => {
  // Arrange
  renderHome(true);
  expect(screen.getAllByLabelText(/순서 바꾸기/)).toHaveLength(5);
  expect(dnd.props, "no DndContext on screen").not.toBeNull();

  // Act
  await act(async () => {
    dnd.props.onDragEnd({ active: { id: "s2" }, over: { id: "s1" } });
    await new Promise((settle) => setTimeout(settle, 0));
  });

  // Assert — this Sunday, its six songs, nothing from the week after
  expect(reorderWeek).toHaveBeenCalledTimes(1);
  expect(reorderWeek).toHaveBeenCalledWith({
    weekOf: SUNDAY,
    scoreIds: ["s2", "s1", "s3", "s4", "s5", "s6"],
  });
});

// AC-24
it("팀원에게는 홈 콘티에 순서 바꾸기 손잡이를 그리지 않아야 한다", () => {
  // Arrange & Act
  const { container } = renderHome(false);

  // Assert — the songs are there, the handles are not
  expect(screen.getByText("곡1")).toBeTruthy();
  expect(screen.queryAllByLabelText(/순서 바꾸기/)).toHaveLength(0);
  expect(container.querySelectorAll("[aria-roledescription]")).toHaveLength(0);
});

// AC-24
it("다른 순서 저장이 진행 중이면 홈 콘티의 손잡이를 잠가야 한다", () => {
  // Arrange — the hook's flag has to reach the card
  useScores.mockReturnValue({ ...hookValue, isReordering: true });

  // Act
  renderHome(true);

  // Assert
  const handles = screen.getAllByLabelText(/순서 바꾸기/);
  expect(handles).toHaveLength(5);
  handles.forEach((handle) => expect(handle.getAttribute("aria-disabled")).toBe("true"));
});

// --- the library card's edit ------------------------------------------------

const UPLOAD_HEADING = "보관함에서 곡을 골라 콘티에 추가하세요";

async function openLibraryEdit() {
  renderHome(true);
  fireEvent.click(screen.getByRole("button", { name: "보관함" }));
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: `${LIBRARY_SONG.title} 수정` }));
  });
}

// AC-311
it("인도자가 보관함에서 곡의 수정을 누르면 그 곡 제목으로 수정 다이얼로그가 열려야 한다", async () => {
  // Arrange & Act
  await openLibraryEdit();

  // Assert — the edit form, seeded with the song; not the placement dialog
  expect(screen.getByLabelText("악보 제목").value).toBe(LIBRARY_SONG.title);
  expect(screen.queryByText(UPLOAD_HEADING)).toBeNull();
});

// AC-312
it("보관함 수정 다이얼로그에서 제목을 바꿔 저장하면 updateSong 을 곡 id 로 한 번 부르고 닫혀야 한다", async () => {
  // Arrange
  await openLibraryEdit();
  fireEvent.change(screen.getByLabelText("악보 제목"), { target: { value: "새 제목" } });

  // Act
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
  });

  // Assert — song_id, not the dialog's scoreId; the week's updateScore untouched
  expect(updateSong).toHaveBeenCalledTimes(1);
  expect(updateSong).toHaveBeenCalledWith({
    songId: LIBRARY_SONG.song_id,
    title: "새 제목",
    file: null,
    currentTitle: LIBRARY_SONG.title,
  });
  expect(hookValue.updateScore).not.toHaveBeenCalled();
  expect(screen.queryByLabelText("악보 제목")).toBeNull();
});

it("보관함 곡 수정이 실패하면 다이얼로그를 열어 둔 채 서버 문구를 보여야 한다", async () => {
  // Arrange
  updateSong.mockResolvedValue({ ok: false, message: "같은 제목의 곡이 이미 있습니다." });
  await openLibraryEdit();
  fireEvent.change(screen.getByLabelText("악보 제목"), { target: { value: "겹치는 제목" } });

  // Act
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "저장" }));
  });

  // Assert
  expect(screen.getByRole("alert").textContent).toBe("같은 제목의 곡이 이미 있습니다.");
  expect(screen.getByLabelText("악보 제목").value).toBe("겹치는 제목");
});

it("보관함 수정 다이얼로그를 취소하면 updateSong 을 부르지 않고 닫혀야 한다", async () => {
  // Arrange
  await openLibraryEdit();

  // Act
  fireEvent.click(screen.getByRole("button", { name: "취소" }));

  // Assert
  expect(screen.queryByLabelText("악보 제목")).toBeNull();
  expect(updateSong).not.toHaveBeenCalled();
});

// AC-313
it("팀원에게는 보관함 탭도 보관함 곡 수정 버튼도 그리지 않아야 한다", () => {
  // Arrange & Act
  renderHome(false);

  // Assert
  expect(screen.queryAllByRole("button", { name: "보관함" })).toHaveLength(0);
  expect(screen.queryByText("악보 보관함")).toBeNull();
  expect(screen.queryByRole("button", { name: `${LIBRARY_SONG.title} 수정` })).toBeNull();
  expect(updateSong).not.toHaveBeenCalled();
});
