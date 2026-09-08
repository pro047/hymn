/**
 * @vitest-environment jsdom
 *
 * The conti screen exists to be trusted: what it shows is what the PDF will
 * print. So the assertions here pin *values* the server sent — the page split,
 * the slot aspect ratio, the exact PATCH body — rather than shapes. A preview
 * that re-paginates in the browser, or a reorder that swaps instead of
 * inserting, still renders "two boxes with songs in them".
 *
 * fireEvent rather than user-event: the package is not a dependency, and native
 * HTML5 drag events have no user-event equivalent anyway.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useNavigate } from "react-router-dom";

import ContiPage from "./conti-page";
import { saveBlobAsFile } from "../lib/download";

// Mocked so the page test never touches jsdom's unimplemented navigation; what
// the download *does* is pinned in lib/download.test.ts instead.
vi.mock("../lib/download", () => ({ saveBlobAsFile: vi.fn() }));

const A = {
  score_id: "a",
  title: "은혜",
  starts_new_page: false,
  image_url: "https://cdn.test/a.png",
};
const B = {
  score_id: "b",
  title: "믿음",
  starts_new_page: false,
  image_url: "https://cdn.test/b.png",
};
// starts_new_page true and no file: the two values that must survive a round
// trip untouched — the break is relayed, the missing image gets a sentence.
const C = { score_id: "c", title: "소망", starts_new_page: true, image_url: null };

const contiOf = (pages, weekOf = "2026-09-13") => ({ week_of: weekOf, slot_ratio: 0.75, pages });

const THREE_SONGS = contiOf([[A, B], [C]]);

// C has no file on purpose (the "악보 파일이 없습니다." case), and the PDF
// endpoint refuses a whole week that contains such a song — so the download
// tests need a week where every song has one.
const C_WITH_FILE = { ...C, image_url: "https://cdn.test/c.png" };
const THREE_SONGS_ALL_WITH_FILES = contiOf([[A, B], [C_WITH_FILE]]);

// Two songs filled page 1 and 소망 spilled over: the split nobody asked for,
// so no song carries a break. Dropping into page 2's blank is what turns one
// on, and this is the layout that has one to turn on.
const C_BREAK_OFF = { ...C_WITH_FILE, starts_new_page: false };
const THREE_SONGS_NO_BREAK = contiOf([[A, B], [C_BREAK_OFF]]);

// The mirror image: page 1 was cut short on purpose, so 믿음 carries the break
// that made page 2 start. Dragging it back into page 1's blank is what clears
// that break — there is no button for it any more.
const B_BREAK_ON = { ...B, starts_new_page: true };
const SPLIT_AFTER_FIRST = contiOf([[A], [B_BREAK_ON, C_BREAK_OFF]]);

// An even song count, which is the case dragging alone cannot edit: every page
// is full, so padSlots emits no blank anywhere and there is no box to drop
// into. The scissors is the only way to split this week.
const D = {
  score_id: "d",
  title: "사랑",
  starts_new_page: false,
  image_url: "https://cdn.test/d.png",
};
const FOUR_SONGS = contiOf([
  [A, B],
  [C_BREAK_OFF, D],
]);

const PDF_BLOB = new Blob(["%PDF-1.4"], { type: "application/pdf" });

function replyOf(reply) {
  const status = reply.status ?? 200;
  // headers included because the PDF filename is read from
  // Content-Disposition first; without them the code under test cannot tell
  // "the server named this file" from "fall back to state".
  const headers = new Headers(reply.headers ?? {});
  return Promise.resolve({
    ok: status < 400,
    status,
    headers,
    json: async () => reply.body ?? {},
    blob: async () => reply.blob ?? PDF_BLOB,
  });
}

/**
 * Routes by URL and method, which is enough: the page speaks to exactly three
 * endpoints. `order` may be a list, consumed one reply per PATCH, so a test can
 * make the server answer with an order the client never sent.
 * Returns the call log — url, method and the parsed body.
 */
function mockApi({ conti = { body: THREE_SONGS }, order = { body: THREE_SONGS }, pdf = {} } = {}) {
  const calls = [];
  const orderReplies = Array.isArray(order) ? [...order] : null;

  vi.stubGlobal(
    "fetch",
    vi.fn((input, init = {}) => {
      const url = String(input);
      const method = init.method ?? "GET";
      calls.push({ url, method, body: init.body ? JSON.parse(init.body) : null });

      let reply;
      if (url.endsWith("/pdf")) reply = pdf;
      else if (method === "PATCH") {
        // The last reply repeats, so an unexpected extra PATCH fails on the
        // call-count assertion rather than on a crash inside the page.
        reply = orderReplies
          ? orderReplies.length > 1
            ? orderReplies.shift()
            : orderReplies[0]
          : order;
      } else reply = conti;

      // A request that never settles — the only way to observe the "in flight"
      // UI, which is otherwise gone by the time an assertion runs.
      if (reply.pending) return new Promise(() => {});
      return replyOf(reply);
    })
  );
  return calls;
}

const renderConti = (path = "/conti/2026-09-13") =>
  render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/conti/:week" element={<ContiPage />} />
      </Routes>
    </MemoryRouter>
  );

/** Moves the route to another week from inside the router, as a link would. */
function WeekNav({ to }) {
  const navigate = useNavigate();
  return (
    <button type="button" onClick={() => navigate(`/conti/${to}`)}>
      주차이동
    </button>
  );
}

const renderContiWithWeekNav = (to) =>
  render(
    <MemoryRouter initialEntries={["/conti/2026-09-13"]}>
      <Routes>
        <Route
          path="/conti/:week"
          element={
            <>
              <WeekNav to={to} />
              <ContiPage />
            </>
          }
        />
      </Routes>
    </MemoryRouter>
  );

const slot = (name) => screen.getByRole("group", { name });
const slotNames = () =>
  screen.getAllByRole("group").map((element) => element.getAttribute("aria-label"));
const patchCalls = (calls) => calls.filter((call) => call.method === "PATCH");

/** Resolves once the first load has painted, so no test asserts on the spinner. */
const waitForLoaded = () => screen.findByRole("group", { name: "은혜" });

beforeEach(() => {
  // apiFetch sends no Authorization header without this, and every stub answers
  // 200 regardless — but a 401 would take the refresh path and endSession(),
  // which is a failure mode worth keeping out of these tests entirely.
  localStorage.setItem("hymn_access_token", "token");
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  localStorage.clear();
});

describe("미리보기", () => {
  it("서버가 나눈 페이지 수만큼 쪽 상자를 그려야 한다", async () => {
    // Arrange & Act — 3 songs over 2 pages. A browser that re-chunked by
    // twos would still make 2 boxes, so the split itself is checked below.
    mockApi();
    renderConti();
    await waitForLoaded();

    // Assert
    expect(
      screen.getAllByRole("region").map((element) => element.getAttribute("aria-label"))
    ).toEqual(["1쪽", "2쪽"]);
  });

  it("곡이 모자란 쪽은 빈 칸으로 채워야 한다", async () => {
    // Arrange & Act
    mockApi();
    renderConti();
    await waitForLoaded();

    // Assert — page 2 holds 소망 alone because its starts_new_page broke there;
    // the second slot is blank, not the next song pulled forward.
    const second = within(screen.getByRole("region", { name: "2쪽" }));
    expect(second.getAllByRole("group").map((el) => el.getAttribute("aria-label"))).toEqual([
      "소망",
      "빈 칸",
    ]);
    const first = within(screen.getByRole("region", { name: "1쪽" }));
    expect(first.getAllByRole("group").map((el) => el.getAttribute("aria-label"))).toEqual([
      "은혜",
      "믿음",
    ]);
  });

  it("칸마다 그 곡의 악보 이미지를 보여줘야 한다", async () => {
    // Arrange & Act
    mockApi();
    renderConti();
    await waitForLoaded();

    // Assert
    const image = within(slot("은혜")).getByRole("img");
    expect([image.getAttribute("src"), image.getAttribute("alt")]).toEqual([
      "https://cdn.test/a.png",
      "은혜",
    ]);
    expect(within(slot("믿음")).getByRole("img").getAttribute("src")).toBe(
      "https://cdn.test/b.png"
    );
  });

  it("칸 비율은 응답의 slot_ratio를 그대로 써야 한다", async () => {
    // Arrange & Act — 0.75 is not the production ratio; a CSS file or a
    // Tailwind class with a hard-coded number cannot make this pass.
    mockApi();
    renderConti();
    await waitForLoaded();

    // Assert — the blank slot is measured too: a page whose only song is short
    // must still reserve a full-size second slot, or the preview lies about
    // where the printed song sits.
    expect(slot("은혜").style.getPropertyValue("--conti-slot-ratio")).toBe("0.75");
    expect(slot("빈 칸").style.getPropertyValue("--conti-slot-ratio")).toBe("0.75");
  });

  it("악보 파일이 없는 곡은 없다고 알려야 한다", async () => {
    // Arrange & Act
    mockApi();
    renderConti();
    await waitForLoaded();

    // Assert
    expect(within(slot("소망")).queryByRole("img")).toBeNull();
    expect(within(slot("소망")).getByText("악보 파일이 없습니다.")).toBeTruthy();
  });
});

describe("순서 변경", () => {
  it("첫 곡은 위로, 마지막 곡은 아래로가 잠겨야 한다", async () => {
    // Arrange & Act
    mockApi();
    renderConti();
    await waitForLoaded();

    // Assert — the ends are locked, the middle is not. Locking everything
    // would also pass a "first is disabled" check on its own.
    expect(screen.getByRole("button", { name: "은혜 위로" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "소망 아래로" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "은혜 아래로" }).disabled).toBe(false);
    expect(screen.getByRole("button", { name: "소망 위로" }).disabled).toBe(false);
  });

  it("곡이 하나뿐이면 위아래가 모두 잠기고 화면은 멀쩡해야 한다", async () => {
    // Arrange & Act
    mockApi({ conti: { body: contiOf([[A]]) } });
    renderConti();
    await waitForLoaded();

    // Assert
    expect(screen.getByRole("button", { name: "은혜 위로" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "은혜 아래로" }).disabled).toBe(true);
    expect(slotNames()).toEqual(["은혜", "빈 칸"]);
  });

  it("아래로는 빈 칸을 건너뛰고 다음 곡과 맞바꿔야 한다", async () => {
    // Arrange — page 1 holds 은혜 alone, so the box right after it is a blank.
    // Stepping into that blank would put 은혜 back where it already is: a
    // button that looks available and sends nothing.
    const calls = mockApi({ conti: { body: SPLIT_AFTER_FIRST } });
    renderConti();
    await waitForLoaded();
    expect(slotNames()).toEqual(["은혜", "빈 칸", "믿음", "소망"]);

    // Act
    fireEvent.click(screen.getByRole("button", { name: "은혜 아래로" }));

    // Assert — 은혜 and 믿음 traded boxes, so 은혜 now starts page 2.
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(1));
    expect(patchCalls(calls)[0].body).toEqual({
      items: [
        { score_id: "b", starts_new_page: false },
        { score_id: "a", starts_new_page: true },
        { score_id: "c", starts_new_page: false },
      ],
    });
  });

  it("아래로를 누르면 그 주차 곡 전체를 바뀐 순서로 보내야 한다", async () => {
    // Arrange
    const calls = mockApi();
    renderConti();
    await waitForLoaded();

    // Act — 믿음 sits in page 1 slot 2; the song after it is 소망, alone on
    // page 2. The two trade boxes.
    fireEvent.click(screen.getByRole("button", { name: "믿음 아래로" }));

    // Assert — every song exactly once, and the breaks are recomputed from
    // where the songs ended up: 소망 joined page 1 so its break is gone, and
    // 믿음 now starts page 2 so it has one. A partial list is a 400 from the
    // server (ContiOrderMismatch).
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(1));
    const [patch] = patchCalls(calls);
    expect(patch.url.endsWith("/weeks/2026-09-13/conti/order")).toBe(true);
    expect(patch.body).toEqual({
      items: [
        { score_id: "a", starts_new_page: false },
        { score_id: "c", starts_new_page: false },
        { score_id: "b", starts_new_page: true },
      ],
    });
  });

  it("응답 순서가 보낸 순서와 달라도 화면은 응답을 따라야 한다", async () => {
    // Arrange — the client asks for [a, c, b]; the server answers [c, a, b].
    // Only a screen drawn from the response can show 소망 first.
    const calls = mockApi({ order: { body: contiOf([[C, A], [B]]) } });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "믿음 아래로" }));

    // Assert
    await waitFor(() => expect(slotNames()).toEqual(["소망", "은혜", "믿음", "빈 칸"]));
    expect(patchCalls(calls)[0].body.items.map((item) => item.score_id)).toEqual(["a", "c", "b"]);
  });

  it("연속으로 옮기면 두 번째 요청은 첫 응답의 순서를 기준으로 해야 한다", async () => {
    // Arrange — the server answers the first move with [은혜, 소망, 믿음].
    const calls = mockApi({ order: [{ body: contiOf([[A, C], [B]]) }, { body: THREE_SONGS }] });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "믿음 아래로" }));
    await waitFor(() => expect(slotNames()).toEqual(["은혜", "소망", "믿음", "빈 칸"]));
    fireEvent.click(screen.getByRole("button", { name: "소망 위로" }));

    // Assert — a handler still closed over the *first* order would read index 1
    // as 믿음 and send [b, a, c].
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(2));
    expect(patchCalls(calls)[1].body.items.map((item) => item.score_id)).toEqual(["c", "a", "b"]);
  });

  it("곡 위에 끌어다 놓으면 자리를 맞바꿔야 한다", async () => {
    // Arrange — 은혜 and 믿음 fill page 1; 소망 is alone on page 2.
    const calls = mockApi();
    renderConti();
    await waitForLoaded();

    // Act — drag 소망 onto 은혜
    fireEvent.dragStart(slot("소망"));
    fireEvent.dragOver(slot("은혜"));
    fireEvent.drop(slot("은혜"));

    // Assert — an insert would send [c, a, b] and push 믿음 onto page 2,
    // moving a song nobody dragged. The swap leaves 믿음 where it was, so
    // both pages keep their size and the layout stays reproducible.
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(1));
    expect(patchCalls(calls)[0].body.items.map((item) => item.score_id)).toEqual(["c", "b", "a"]);
  });

  it("빈 칸에 끌어다 놓으면 그 쪽으로 옮기고 나누기를 켜야 한다", async () => {
    // Arrange — the automatic split: 은혜·믿음 on page 1, 소망 spilled onto
    // page 2, nobody carrying a break.
    const calls = mockApi({ conti: { body: THREE_SONGS_NO_BREAK } });
    renderConti();
    await waitForLoaded();

    // Act — drop 믿음 into page 2's blank
    fireEvent.dragStart(slot("믿음"));
    fireEvent.dragOver(slot("빈 칸"));
    fireEvent.drop(slot("빈 칸"));

    // Assert — [은혜] [소망, 믿음]. Only a break on 소망 reproduces a page
    // holding one song, and chunk_pages would otherwise glue 은혜 and 소망
    // back together — so this flag is the whole reason the layout survives.
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(1));
    expect(patchCalls(calls)[0].body).toEqual({
      items: [
        { score_id: "a", starts_new_page: false },
        { score_id: "c", starts_new_page: true },
        { score_id: "b", starts_new_page: false },
      ],
    });
  });

  it("앞 쪽 빈 칸으로 끌어오면 나누기가 꺼져야 한다", async () => {
    // Arrange — page 1 was cut short on purpose, so 믿음 carries the break.
    // There is no button to clear it; dragging is the only way.
    const calls = mockApi({ conti: { body: SPLIT_AFTER_FIRST } });
    renderConti();
    await waitForLoaded();

    // Act — drop 믿음 into page 1's blank
    fireEvent.dragStart(slot("믿음"));
    fireEvent.dragOver(slot("빈 칸"));
    fireEvent.drop(slot("빈 칸"));

    // Assert — [은혜, 믿음] [소망]: 믿음 stopped starting a page, so its break
    // is gone, and 소망 now starts one. A relayed flag would send true for
    // 믿음 and split the page the leader just closed.
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(1));
    expect(patchCalls(calls)[0].body).toEqual({
      items: [
        { score_id: "a", starts_new_page: false },
        { score_id: "b", starts_new_page: false },
        { score_id: "c", starts_new_page: true },
      ],
    });
  });

  it("자기 쪽의 빈 칸에 놓으면 아무 요청도 보내지 않아야 한다", async () => {
    // Arrange — 소망 is alone on page 2, and the blank beside it is its own
    // page's. Moving there changes neither the order nor the pages.
    const calls = mockApi();
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.dragStart(slot("소망"));
    fireEvent.dragOver(slot("빈 칸"));
    fireEvent.drop(slot("빈 칸"));

    // Assert — synchronous on purpose: apiFetch calls fetch before its first
    // await, so a request, if sent, would already be in the log.
    expect(patchCalls(calls)).toHaveLength(0);
  });

  it("같은 이동이면 드래그와 버튼이 같은 요청을 보내야 한다", async () => {
    // Arrange & Act — move 믿음 down one, by button
    const buttonCalls = mockApi();
    renderConti();
    await waitForLoaded();
    fireEvent.click(screen.getByRole("button", { name: "믿음 아래로" }));
    await waitFor(() => expect(patchCalls(buttonCalls)).toHaveLength(1));

    cleanup();
    vi.unstubAllGlobals();

    // Act — the same move, by drag
    const dragCalls = mockApi();
    renderConti();
    await waitForLoaded();
    fireEvent.dragStart(slot("믿음"));
    fireEvent.dragOver(slot("소망"));
    fireEvent.drop(slot("소망"));
    await waitFor(() => expect(patchCalls(dragCalls)).toHaveLength(1));

    // Assert — two ways in, one reorder function. A second copy of the logic
    // behind the drag path would drift from the buttons here.
    expect(patchCalls(dragCalls)[0].body).toEqual(patchCalls(buttonCalls)[0].body);
  });

  it("제자리에 놓으면 아무 요청도 보내지 않아야 한다", async () => {
    // Arrange
    const calls = mockApi();
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.dragStart(slot("믿음"));
    fireEvent.dragOver(slot("믿음"));
    fireEvent.drop(slot("믿음"));

    // Assert — synchronous on purpose: apiFetch calls fetch before its first
    // await, so a request, if sent, would already be in the log.
    expect(patchCalls(calls)).toHaveLength(0);
  });

  it("끌기 없이 놓기만 일어나면 아무 요청도 보내지 않아야 한다", async () => {
    // Arrange — a drop whose drag started outside the preview (or a second drop
    // after the position was consumed) has no source box to move.
    const calls = mockApi();
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.drop(slot("은혜"));
    fireEvent.dragStart(slot("소망"));
    fireEvent.drop(slot("은혜"));
    fireEvent.drop(slot("믿음"));

    // Assert — exactly one move: the third drop finds the ref already cleared.
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(1));
    expect(patchCalls(calls)[0].body.items.map((item) => item.score_id)).toEqual(["c", "b", "a"]);
  });

  it("저장에 실패하면 서버 문구를 보이고 순서는 그대로여야 한다", async () => {
    // Arrange
    const calls = mockApi({
      order: { status: 400, body: { detail: "콘티에 있는 모든 곡을 보내야 합니다." } },
    });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "믿음 아래로" }));

    // Assert — no optimistic update to roll back, so the screen never moved.
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("콘티에 있는 모든 곡을 보내야 합니다.");
    expect(slotNames()).toEqual(["은혜", "믿음", "소망", "빈 칸"]);
    // And the screen is usable again — a stuck isSaving would lock every move.
    expect(screen.getByRole("button", { name: "믿음 아래로" }).disabled).toBe(false);
    expect(patchCalls(calls)).toHaveLength(1);
  });

  it("실패한 뒤 성공하면 이전 오류 문구가 사라져야 한다", async () => {
    // Arrange — the first PATCH is rejected, the second is accepted. One alert
    // slot is shared by load/save/PDF, so a stale message left behind would
    // read as if the move that just worked had failed.
    mockApi({
      order: [
        { status: 400, body: { detail: "콘티에 있는 모든 곡을 보내야 합니다." } },
        { body: contiOf([[C, A], [B]]) },
      ],
    });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "믿음 아래로" }));
    await screen.findByRole("alert");
    fireEvent.click(screen.getByRole("button", { name: "믿음 아래로" }));

    // Assert
    await waitFor(() => expect(slotNames()).toEqual(["소망", "은혜", "믿음", "빈 칸"]));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("저장하는 동안 순서 버튼이 잠겨야 한다", async () => {
    // Arrange
    mockApi({ order: { pending: true } });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "믿음 아래로" }));

    // Assert — the two that were enabled before the click are now locked, so a
    // second reorder cannot race the first.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "은혜 아래로" }).disabled).toBe(true)
    );
    expect(screen.getByRole("button", { name: "소망 위로" }).disabled).toBe(true);
  });
});

describe("빈 주차", () => {
  it("곡이 없으면 안내만 보이고 오류로 다루지 않아야 한다", async () => {
    // Arrange & Act — the server answers 200 with pages: [], not 404.
    mockApi({ conti: { body: contiOf([]) } });
    renderConti();

    // Assert
    expect(await screen.findByText("아직 등록된 곡이 없습니다.")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("곡이 없으면 PDF 버튼을 그리지 않아야 한다", async () => {
    // Arrange & Act — GET /weeks/{week}/pdf answers 404 for an empty week, so
    // an offered button could only turn "no songs yet" into a failure message.
    mockApi({ conti: { body: contiOf([]) } });
    renderConti();
    await screen.findByText("아직 등록된 곡이 없습니다.");

    // Assert
    expect(screen.queryByRole("button", { name: "PDF 내려받기" })).toBeNull();
  });
});

describe("PDF 내려받기", () => {
  it("그 주차의 PDF를 요청해야 한다", async () => {
    // Arrange
    const calls = mockApi({ conti: { body: THREE_SONGS_ALL_WITH_FILES } });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "PDF 내려받기" }));

    // Assert
    await waitFor(() => expect(calls.some((call) => call.url.endsWith("/pdf"))).toBe(true));
    const pdfCall = calls.find((call) => call.url.endsWith("/pdf"));
    expect(pdfCall.url.endsWith("/weeks/2026-09-13/pdf")).toBe(true);
    expect(pdfCall.method).toBe("GET");
  });

  it("받은 내용을 주차 이름의 파일로 저장해야 한다", async () => {
    // Arrange
    mockApi({ conti: { body: THREE_SONGS_ALL_WITH_FILES }, pdf: { blob: PDF_BLOB } });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "PDF 내려받기" }));

    // Assert
    await waitFor(() => expect(saveBlobAsFile).toHaveBeenCalled());
    expect(saveBlobAsFile.mock.calls).toEqual([[PDF_BLOB, "conti-2026-09-13.pdf"]]);
  });

  it("주소가 주중 날짜여도 파일명은 응답의 일요일이어야 한다", async () => {
    // Arrange — the server normalizes 2026-09-09 (a Wednesday) to that week's
    // Sunday and prints the Sunday's PDF. A filename built from the URL would
    // label it with a day the file never mentions.
    const calls = mockApi({ conti: { body: contiOf([[A, B], [C_WITH_FILE]], "2026-09-13") } });
    renderConti("/conti/2026-09-09");
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "PDF 내려받기" }));

    // Assert
    await waitFor(() => expect(saveBlobAsFile).toHaveBeenCalled());
    expect(saveBlobAsFile.mock.calls[0][1]).toBe("conti-2026-09-13.pdf");
    // The request itself still carries the URL's date — normalizing is the
    // server's job and doing it twice would be a second source of truth.
    expect(calls.find((call) => call.url.endsWith("/pdf")).url).toContain("/weeks/2026-09-09/pdf");
    expect(screen.getByRole("heading", { name: "2026-09-13 콘티" })).toBeTruthy();
  });

  it("만드는 동안 버튼이 잠기고 진행 중임을 알려야 한다", async () => {
    // Arrange — the PDF takes seconds to render; without this the leader
    // cannot tell a slow request from a dead button and clicks again.
    mockApi({ conti: { body: THREE_SONGS_ALL_WITH_FILES }, pdf: { pending: true } });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "PDF 내려받기" }));

    // Assert
    const button = await screen.findByRole("button", { name: "PDF 만드는 중…" });
    expect(button.disabled).toBe(true);
    expect(screen.queryByRole("button", { name: "PDF 내려받기" })).toBeNull();
  });

  it("PDF가 실패하면 문구를 보이고 진행 표시를 풀어야 한다", async () => {
    // Arrange
    mockApi({
      conti: { body: THREE_SONGS_ALL_WITH_FILES },
      pdf: { status: 502, body: { detail: "PDF를 만들지 못했습니다." } },
    });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "PDF 내려받기" }));

    // Assert
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("PDF를 만들지 못했습니다.");
    const button = screen.getByRole("button", { name: "PDF 내려받기" });
    expect(button.disabled).toBe(false);
    expect(saveBlobAsFile).not.toHaveBeenCalled();
  });
});

describe("첫 로드", () => {
  it("아직 응답이 없으면 불러오는 중임을 알려야 한다", () => {
    // Arrange & Act — the request never settles, which is the only way to hold
    // the screen in its first-load state long enough to look at it.
    mockApi({ conti: { pending: true } });
    renderConti();

    // Assert — and specifically not the empty-week notice: pages is null, not
    // [], and a screen that treated the two the same would tell the leader
    // there are no songs every time the network is slow.
    expect(screen.getByText("콘티를 불러오는 중…")).toBeTruthy();
    expect(screen.queryByText("아직 등록된 곡이 없습니다.")).toBeNull();
    expect(screen.queryByRole("button", { name: "PDF 내려받기" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("불러오기 실패", () => {
  it("콘티를 못 불러오면 서버 문구를 보여줘야 한다", async () => {
    // Arrange & Act
    mockApi({ conti: { status: 500, body: { detail: "콘티를 불러오지 못했습니다." } } });
    renderConti();

    // Assert — and nothing that would imply an answer arrived.
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("콘티를 불러오지 못했습니다.");
    expect(screen.queryAllByRole("region")).toEqual([]);
    expect(screen.queryByText("아직 등록된 곡이 없습니다.")).toBeNull();
  });

  it("요청 자체가 실패하면 네트워크 오류를 알려야 한다", async () => {
    // Arrange — fetch rejects: no status, no body, nothing readApiError can read.
    vi.stubGlobal(
      "fetch",
      vi.fn(() => Promise.reject(new TypeError("Failed to fetch")))
    );

    // Act
    renderConti();

    // Assert
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("네트워크 오류로 요청에 실패했습니다.");
  });
});

// --- code review 2026-09-07: findings pinned here --------------------------

describe("코드리뷰 반영", () => {
  it("악보 파일이 없는 곡이 있으면 PDF 버튼 대신 이유를 보여야 한다", async () => {
    // Arrange — build_week_conti_pdf refuses the whole week with 502 when any
    // song has no file, so a button here could only ever fail.
    mockApi({ conti: { body: THREE_SONGS } }); // C has image_url: null
    renderConti();
    await waitForLoaded();

    // Act & Assert
    expect(screen.queryByRole("button", { name: "PDF 내려받기" })).toBeNull();
    // Named in the notice, not just counted: the leader has to know which song
    // to re-upload. "소망" also labels its own slot, so the assertion reads the
    // notice's own text rather than searching the page for the title.
    const notice = screen.getByText(/악보 파일이 없는 곡이 있어/);
    expect(notice.textContent).toContain("소망");
  });

  it("저장 중에는 곡을 끌 수 없어야 한다", async () => {
    // Arrange — gating only the buttons left the drag path open, so a second
    // reorder could be computed from the pre-move list and land last.
    let releaseOrder;
    mockApi({
      conti: { body: THREE_SONGS_ALL_WITH_FILES },
      order: { body: THREE_SONGS_ALL_WITH_FILES, wait: new Promise((r) => (releaseOrder = r)) },
    });
    renderConti();
    await waitForLoaded();

    // Act — start a save and look at the slot while it is in flight
    fireEvent.click(screen.getByRole("button", { name: "은혜 아래로" }));

    // Assert
    await waitFor(() => expect(slot("은혜").getAttribute("draggable")).toBe("false"));
    releaseOrder?.();
  });

  it("PDF 파일명은 서버가 붙인 이름을 따라야 한다", async () => {
    // Arrange — the header names a week the client never holds, so this fails
    // for any implementation that builds the name from its own state.
    //
    // ASCII on purpose: Headers rejects non-ISO-8859-1 values with a
    // TypeError, which downloadPdf's catch would report as a network error.
    //
    // The real hazard it guards is narrower: `weekOf` starts as the URL param
    // and is only corrected by a successful conti GET, so a name from state
    // could label a Sunday file with a Wednesday. That exact sequence is not
    // reachable through the screen today (a failed GET renders no button), so
    // the fixture makes the two sources disagree on purpose rather than
    // reproducing it.
    mockApi({
      conti: { body: THREE_SONGS_ALL_WITH_FILES },
      pdf: {
        headers: { "Content-Disposition": 'attachment; filename="conti-named-by-server.pdf"' },
      },
    });
    renderConti("/conti/2026-09-09");
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "PDF 내려받기" }));

    // Assert
    await waitFor(() => expect(saveBlobAsFile).toHaveBeenCalled());
    expect(saveBlobAsFile.mock.calls[0][1]).toBe("conti-named-by-server.pdf");
  });

  it("가위는 쪽 안의 곡 사이에만 있고 쪽 사이·첫 곡 앞에는 없어야 한다", async () => {
    // Arrange — [은혜, 믿음] [소망]. The only seam inside a page is 은혜|믿음.
    // 소망 opens page 2, so there is nothing to cut in front of it; closing
    // that split back up is what dragging it into page 1's blank does.
    mockApi({ conti: { body: THREE_SONGS_NO_BREAK } });
    renderConti();
    await waitForLoaded();

    // Act & Assert
    expect(
      screen.getAllByRole("button", { name: /나누기/ }).map((b) => b.getAttribute("aria-label"))
    ).toEqual(["믿음 앞에서 나누기"]);
    expect(screen.queryByRole("button", { name: /은혜 앞/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /소망 앞/ })).toBeNull();
  });

  it("쪽이 전부 꽉 찬 주차도 가위로 나눌 수 있어야 한다", async () => {
    // Arrange — 4 songs, so every page is full and padSlots emits no blank at
    // all. Dragging can only swap here; without the scissors this week could
    // never be split. This is the case the code review found unreachable.
    const calls = mockApi({ conti: { body: FOUR_SONGS } });
    renderConti();
    await waitForLoaded();
    expect(screen.queryAllByRole("group", { name: "빈 칸" })).toEqual([]);

    // Act — cut in front of 믿음
    fireEvent.click(screen.getByRole("button", { name: "믿음 앞에서 나누기" }));

    // Assert — one seam added, the running order untouched. 소망's flag stays
    // false: page 2 started there because page 1 filled up, not because anyone
    // asked, and freezing that in would answer [은혜][믿음][소망,사랑] — two
    // cuts for one click.
    await waitFor(() => expect(patchCalls(calls)).toHaveLength(1));
    expect(patchCalls(calls)[0].body).toEqual({
      items: [
        { score_id: "a", starts_new_page: false },
        { score_id: "b", starts_new_page: true },
        { score_id: "c", starts_new_page: false },
        { score_id: "d", starts_new_page: false },
      ],
    });
  });

  it("주차를 옮긴 뒤 도착한 이전 주차의 응답을 그리지 않아야 한다", async () => {
    // Arrange — the PATCH for week A is held open, the route moves to week B,
    // B's GET lands first, and only then does A's PATCH answer. Without a
    // guard that late response repaints week A's conti under week B's URL,
    // and the next drag would PATCH B with A's score_ids for a 400.
    let answerPatch;
    const heldPatch = new Promise((resolve) => {
      answerPatch = resolve;
    });
    vi.stubGlobal(
      "fetch",
      vi.fn((input, init = {}) => {
        const url = String(input);
        if ((init.method ?? "GET") === "PATCH") return heldPatch;
        if (url.includes("2026-09-20")) return replyOf({ body: contiOf([[D]], "2026-09-20") });
        return replyOf({ body: THREE_SONGS });
      })
    );
    renderContiWithWeekNav("2026-09-20");
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "믿음 아래로" }));
    fireEvent.click(screen.getByRole("button", { name: "주차이동" }));
    await screen.findByRole("group", { name: "사랑" });
    answerPatch(await replyOf({ body: THREE_SONGS }));

    // Assert — week B stays on screen. 은혜 belongs to week A and must not
    // come back.
    await waitFor(() => expect(slotNames()).toEqual(["사랑", "빈 칸"]));
    expect(screen.queryByRole("group", { name: "은혜" })).toBeNull();
  });

  it("저장 중에는 가위가 잠겨야 한다", async () => {
    // Arrange
    mockApi({ conti: { body: FOUR_SONGS }, order: { pending: true } });
    renderConti();
    await waitForLoaded();

    // Act
    fireEvent.click(screen.getByRole("button", { name: "은혜 아래로" }));

    // Assert
    await waitFor(() =>
      expect(screen.getAllByRole("button", { name: /나누기/ }).every((b) => b.disabled)).toBe(true)
    );
  });

  it("저장 중에는 빈 칸이 드롭을 받지 않아야 한다", async () => {
    // Arrange — the buttons are disabled during a save, and the drop path has
    // to close with them: a second edit computed from the pre-save layout
    // would land after the first response and win.
    const calls = mockApi({
      conti: { body: THREE_SONGS_NO_BREAK },
      order: { pending: true },
    });
    renderConti();
    await waitForLoaded();

    // Act — start a save, then try to drop into the blank while it is in
    // flight. dragStart is fired first so the source is set either way.
    fireEvent.dragStart(slot("믿음"));
    fireEvent.click(screen.getByRole("button", { name: "은혜 아래로" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "은혜 아래로" }).disabled).toBe(true)
    );
    fireEvent.drop(slot("빈 칸"));

    // Assert — still just the one PATCH the button started.
    expect(patchCalls(calls)).toHaveLength(1);
  });
});
