/** @vitest-environment jsdom */

/**
 * Pins that 콘티 offers only actions that exist.
 *
 * 섞기 and 발행 sat here as <Button> elements with no onClick at all — they
 * rendered, took a click, and did nothing. 발행 still has no backend
 * (status is written 'draft' once, never changed, and ScoreResponse does not
 * carry it). Reordering now does: PATCH /weeks/{week}/conti/order, reached
 * through a drag handle on each row and drawn only when the page hands the
 * card an onReorder for a leader.
 *
 * Drops are delivered by calling the DndContext's onDragEnd directly. jsdom
 * gives every element a zero-sized box, so a pointer drag cannot land on a
 * particular row; what is tested is what the card does with a drop.
 */

import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

import StageCard from "./stage-card";

/** The props of the DndContext on screen, so a test can hand it a drop. */
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

const SCORES = [
  { id: "s1", title: "은혜", week_of: "2026-08-23" },
  { id: "s2", title: "믿음", week_of: "2026-08-23" },
];

function renderCard(overrides = {}) {
  const onUpdate = vi.fn();
  const onDelete = vi.fn();
  render(
    // The card links to the conti editor, so it needs a router above it.
    <MemoryRouter>
      <StageCard
        scores={SCORES}
        weekOf="2026-08-23"
        onUpdate={onUpdate}
        onDelete={onDelete}
        {...overrides}
      />
    </MemoryRouter>
  );
  return { onUpdate, onDelete };
}

afterEach(cleanup);

it("동작하지 않는 섞기·발행 버튼을 보여주지 않아야 한다", () => {
  // Arrange & Act
  renderCard();

  // Assert
  expect(screen.queryByRole("button", { name: "섞기" })).toBeNull();
  expect(screen.queryByRole("button", { name: "발행" })).toBeNull();
});

it("남은 버튼은 모두 눌렀을 때 실제로 무언가를 해야 한다", () => {
  // Arrange — the general rule the two removals were an instance of.
  const { onUpdate, onDelete } = renderCard();

  // Act — click every button the card renders.
  const buttons = screen.getAllByRole("button");
  buttons.forEach((button) => fireEvent.click(button));

  // Assert — 2 rows x (제목 + 수정 + 삭제); every click reached a handler.
  expect(buttons.length).toBe(6);
  expect(onUpdate.mock.calls.length + onDelete.mock.calls.length).toBe(buttons.length);
});

it("악보를 누르면 그 악보 객체를 통째로 넘겨야 한다", () => {
  // Arrange — the edit dialog needs title and download_url, not just the id.
  const { onUpdate } = renderCard();

  // Act
  fireEvent.click(screen.getByRole("button", { name: "은혜" }));

  // Assert
  expect(onUpdate).toHaveBeenCalledWith(SCORES[0]);
});

it("돌아오는 일요일 주차를 표시해야 한다", () => {
  // Arrange & Act
  renderCard();

  // Assert
  expect(screen.getByText(/2026-08-23/)).toBeTruthy();
});

it("콘티 편집은 그 주차의 편집 화면을 가리켜야 한다", () => {
  // Arrange & Act — a link, not a button, so the 6-button assertion above
  // still holds and the leader can open the editor in a new tab.
  renderCard();

  // Assert — the week travels in the URL; a link to a bare /conti would land
  // on the catch-all route and bounce home with no error.
  expect(screen.getByRole("link", { name: "콘티 편집" }).getAttribute("href")).toBe(
    "/conti/2026-08-23"
  );
});

it("악보가 없어도 콘티 편집으로 갈 수 있어야 한다", () => {
  // Arrange & Act — an empty week is where a leader most wants the editor;
  // the conti screen answers 200 with "아직 등록된 곡이 없습니다.", not an error.
  renderCard({ scores: [] });

  // Assert
  expect(screen.getByRole("link", { name: "콘티 편집" })).toBeTruthy();
});

it("악보가 없으면 빈 상태를 안내해야 한다", () => {
  // Arrange & Act
  renderCard({ scores: [] });

  // Assert
  expect(screen.getByText(/악보가 없습니다/)).toBeTruthy();
});

it("보관함은 교회의 모든 곡이라 저장 버튼을 보여주지 않아야 한다", () => {
  // Arrange
  renderCard({
    scores: [{ id: "u1", song_id: "song-1", title: "은혜", week_of: "2026-08-23" }],
  });

  // Assert
  expect(screen.queryByRole("button", { name: /저장/ })).toBeNull();
});

it("관리 권한이 없으면 수정·삭제·콘티 편집을 보여주지 않아야 한다", () => {
  // Arrange & Act
  renderCard({ canManage: false });

  // Assert — the songs are still listed; only the ways to change them are gone.
  expect(screen.getByText("은혜")).toBeTruthy();
  expect(screen.getByText("믿음")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "수정" })).toBeNull();
  expect(screen.queryByRole("button", { name: "삭제" })).toBeNull();
  expect(screen.queryByRole("link", { name: "콘티 편집" })).toBeNull();
});

it("관리 권한이 없으면 제목을 눌러도 수정이 열리지 않아야 한다", () => {
  // Arrange
  const { onUpdate } = renderCard({ canManage: false });

  // Act
  fireEvent.click(screen.getByText("은혜"));

  // Assert
  expect(onUpdate).not.toHaveBeenCalled();
});

// --- drag to reorder (leader only) ---------------------------------------

const SIX = [1, 2, 3, 4, 5, 6].map((n) => ({
  id: `s${n}`,
  title: `곡${n}`,
  week_of: "2026-08-23",
}));

const titlesOnScreen = () => screen.getAllByText(/^곡\d$/).map((element) => element.textContent);

/** A promise the test settles by hand, so "while saving" can be looked at. */
function deferred() {
  let resolve;
  const promise = new Promise((settle) => {
    resolve = settle;
  });
  return { promise, resolve };
}

function renderReorderable(overrides = {}) {
  const onReorder = overrides.onReorder ?? vi.fn(async () => ({ ok: true, saved: true }));
  const props = {
    scores: SIX,
    weekOf: "2026-08-23",
    onUpdate: vi.fn(),
    onDelete: vi.fn(),
    canManage: true,
    isReordering: false,
    ...overrides,
    onReorder,
  };
  const view = render(
    <MemoryRouter>
      <StageCard {...props} />
    </MemoryRouter>
  );
  const rerender = (next) =>
    view.rerender(
      <MemoryRouter>
        <StageCard {...props} {...next} />
      </MemoryRouter>
    );
  return { onReorder, rerender };
}

/** Hands the card a drop and lets every promise already settled run out.
 *
 * The handler is not awaited: with onReorder held open it would never return,
 * and "while saving" is exactly what some tests look at. */
async function drop(activeId, overId) {
  expect(dnd.props, "no DndContext on screen").not.toBeNull();
  await act(async () => {
    dnd.props.onDragEnd({
      active: { id: activeId },
      over: overId === null ? null : { id: overId },
    });
    await new Promise((settle) => setTimeout(settle, 0));
  });
}

beforeEach(() => {
  dnd.props = null;
});

// AC-16
it("인도자에게는 보이는 곡마다 순서 바꾸기 손잡이를 하나씩 보여줘야 한다", () => {
  // Arrange & Act — six songs, five drawn
  renderReorderable();

  // Assert
  for (const n of [1, 2, 3, 4, 5]) {
    expect(screen.getAllByLabelText(`곡${n} 순서 바꾸기`)).toHaveLength(1);
  }
  expect(screen.queryAllByLabelText("곡6 순서 바꾸기")).toHaveLength(0);
  expect(screen.getAllByLabelText(/순서 바꾸기/)).toHaveLength(5);
});

// AC-17
it("관리 권한이 없으면 손잡이도 정렬 속성도 그리지 않아야 한다", () => {
  // Arrange & Act
  const { container } = render(
    <MemoryRouter>
      <StageCard
        scores={SIX}
        weekOf="2026-08-23"
        onUpdate={vi.fn()}
        onDelete={vi.fn()}
        onReorder={vi.fn()}
        canManage={false}
      />
    </MemoryRouter>
  );

  // Assert
  expect(screen.queryAllByLabelText(/순서 바꾸기/)).toHaveLength(0);
  expect(container.querySelectorAll("[aria-roledescription]")).toHaveLength(0);
});

// AC-17
it("onReorder 가 없으면 인도자에게도 손잡이를 그리지 않아야 한다", () => {
  // Arrange & Act
  const { container } = render(
    <MemoryRouter>
      <StageCard scores={SIX} weekOf="2026-08-23" onUpdate={vi.fn()} onDelete={vi.fn()} canManage />
    </MemoryRouter>
  );

  // Assert
  expect(screen.queryAllByLabelText(/순서 바꾸기/)).toHaveLength(0);
  expect(container.querySelectorAll("[aria-roledescription]")).toHaveLength(0);
});

// AC-18
it("곡을 다른 곡 위에 놓으면 주차 전체의 새 순서로 onReorder 를 불러야 한다", async () => {
  // Arrange
  const { onReorder } = renderReorderable();

  // Act
  await drop("s3", "s1");

  // Assert — s6 is not drawn but still travels, behind the rest
  expect(onReorder).toHaveBeenCalledTimes(1);
  expect(onReorder).toHaveBeenCalledWith(["s3", "s1", "s2", "s4", "s5", "s6"]);
});

// AC-18
it("같은 자리에 놓거나 놓을 곳이 없으면 onReorder 를 부르지 않아야 한다", async () => {
  // Arrange
  const { onReorder } = renderReorderable();

  // Act
  await drop("s2", "s2");
  await drop("s2", null);

  // Assert
  expect(onReorder).not.toHaveBeenCalled();
  expect(titlesOnScreen()).toEqual(["곡1", "곡2", "곡3", "곡4", "곡5"]);
});

// AC-19
it("다른 저장이 진행 중이면 손잡이를 잠그고 놓아도 onReorder 를 부르지 않아야 한다", async () => {
  // Arrange
  const { onReorder } = renderReorderable({ isReordering: true });

  // Act
  await drop("s3", "s1");

  // Assert
  const handles = screen.getAllByLabelText(/순서 바꾸기/);
  expect(handles).toHaveLength(5);
  handles.forEach((handle) => expect(handle.getAttribute("aria-disabled")).toBe("true"));
  expect(onReorder).not.toHaveBeenCalled();
  expect(titlesOnScreen()).toEqual(["곡1", "곡2", "곡3", "곡4", "곡5"]);
});

// AC-20
it("저장하는 동안 놓은 순서를 보여주고 두 번째 드롭은 무시해야 한다", async () => {
  // Arrange
  const pending = deferred();
  const onReorder = vi.fn(() => pending.promise);
  renderReorderable({ onReorder });

  // Act
  await drop("s3", "s1");
  const whileSaving = titlesOnScreen();
  await drop("s5", "s1");

  // Assert
  expect(whileSaving).toEqual(["곡3", "곡1", "곡2", "곡4", "곡5"]);
  expect(onReorder).toHaveBeenCalledTimes(1);
  expect(titlesOnScreen()).toEqual(["곡3", "곡1", "곡2", "곡4", "곡5"]);

  await act(async () => {
    pending.resolve({ ok: true, saved: true });
    await pending.promise;
  });
});

// AC-20
it("저장되지 않으면 받은 scores 순서로 돌아가야 한다", async () => {
  // Arrange
  const pending = deferred();
  renderReorderable({ onReorder: vi.fn(() => pending.promise) });
  await drop("s3", "s1");

  // Act
  await act(async () => {
    pending.resolve({ ok: false, saved: false, message: "실패" });
    await pending.promise;
  });

  // Assert
  expect(titlesOnScreen()).toEqual(["곡1", "곡2", "곡3", "곡4", "곡5"]);
});

// AC-20
it("저장이 끝나면 다음 드롭을 다시 받아야 한다", async () => {
  // Arrange — the lock is for the save in flight, not for good
  const { onReorder } = renderReorderable({
    onReorder: vi.fn(async () => ({ ok: false, saved: false })),
  });
  await drop("s3", "s1");

  // Act
  await drop("s2", "s1");

  // Assert
  expect(onReorder).toHaveBeenCalledTimes(2);
  expect(onReorder).toHaveBeenLastCalledWith(["s2", "s1", "s3", "s4", "s5", "s6"]);
});

// AC-26
it("저장은 됐지만 목록을 못 다시 읽었으면 같은 scores 로 다시 그려도 놓은 순서를 지켜야 한다", async () => {
  // Arrange
  const { rerender } = renderReorderable({
    onReorder: vi.fn(async () => ({ ok: false, saved: true, message: "다시 못 읽음" })),
  });
  await drop("s3", "s1");

  // Act — the page re-renders with the very same array it had
  rerender({ scores: SIX });

  // Assert — the server holds this order; going back would show a lie
  expect(titlesOnScreen()).toEqual(["곡3", "곡1", "곡2", "곡4", "곡5"]);
});

// AC-26
it("놓은 순서를 지키다가 새 scores 배열이 오면 그 순서를 따라야 한다", async () => {
  // Arrange
  const { rerender } = renderReorderable({
    onReorder: vi.fn(async () => ({ ok: false, saved: true, message: "다시 못 읽음" })),
  });
  await drop("s3", "s1");

  // Act — a fresh list from the server, in an order of its own
  const fresh = [SIX[4], SIX[3], SIX[2], SIX[1], SIX[0], SIX[5]];
  rerender({ scores: fresh });

  // Assert
  expect(titlesOnScreen()).toEqual(["곡5", "곡4", "곡3", "곡2", "곡1"]);
});

// AC-26
it("저장과 재조회가 모두 되면 새로 받은 scores 순서를 따라야 한다", async () => {
  // Arrange
  const { rerender } = renderReorderable();
  await drop("s3", "s1");

  // Act — the hook replaces the list after a successful re-read
  const fresh = [SIX[2], SIX[0], SIX[1], SIX[3], SIX[4], SIX[5]];
  rerender({ scores: fresh });

  // Assert
  expect(titlesOnScreen()).toEqual(["곡3", "곡1", "곡2", "곡4", "곡5"]);
});
