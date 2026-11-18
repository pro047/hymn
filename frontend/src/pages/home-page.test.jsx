/** @vitest-environment jsdom */

/**
 * Pins the wire from the home page to the score hook for a drag on 콘티.
 *
 * The card knows only the songs it was handed and the hook knows only what
 * it is asked to save; what joins them is the page — which week the card is
 * showing, and that the order sent names that week's songs and no other.
 * The hook and the week are replaced so the page is the only thing under test.
 */

import { act, cleanup, render, screen } from "@testing-library/react";
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

let reorderWeek;
let hookValue;

beforeEach(() => {
  dnd.props = null;
  reorderWeek = vi.fn(async () => ({ ok: true, saved: true }));
  hookValue = {
    scores: SCORES,
    totalSongs: 7,
    librarySongs: [],
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
