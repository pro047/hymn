/** @vitest-environment jsdom */

/**
 * Pins the order of the three calls a file replacement makes.
 *
 * Sign, upload, then PATCH. The order is the whole safety property: the row
 * moves onto the new key only after the bytes are in the bucket, so an upload
 * that dies leaves the score pointing at the file it already had. Reversed, a
 * failed PUT would leave a score whose image 404s.
 *
 * A title-only edit must skip the first two entirely — asking for an upload URL
 * it never uses would litter the bucket with keys nothing references.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

import { apiFetch } from "../../../api/client";
import { API_PATHS } from "../../../api/paths";
import { useScores } from "./use-scores";

vi.mock("../../../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../../../lib/auth-storage", () => ({ isAuthenticated: () => true }));

const ok = (body) => ({ ok: true, json: async () => body });

const SIGNED = { upload_url: "https://s3.example.com/put?sig=1", s3_key: "scores/c1/new.png" };
const IMAGE = () => new File(["x"], "rescan.png", { type: "image/png" });

/** Records every call as "METHOD path" so order can be asserted in one array. */
let calls;

function trace(method, url) {
  calls.push(`${method} ${String(url).replace(/^.*?(?=\/scores|\/songs|https:)/, "")}`);
}

const isScoreListRequest = (url, options = {}) =>
  String(url).endsWith("/scores") && (options.method ?? "GET") === "GET";

/** The default apiFetch, with the score list answering `items`. */
function apiFetchListing(items) {
  return async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    if (String(url).endsWith("/file")) return ok(SIGNED);
    // The mount fetches both lists through apiFetch, and the hook keeps
    // whatever comes back: the score list is mapped over on every render, the
    // library is what the library tab and the dialog draw.
    if (isScoreListRequest(url, options)) return ok(items);
    if (String(url).endsWith("/songs") && (options.method ?? "GET") === "GET") return ok([]);
    return ok({ id: "score-1" });
  };
}

/** The body of the PATCH, wherever it falls among the calls around it. */
function patchBody() {
  const patch = apiFetch.mock.calls.find(([, options]) => options?.method === "PATCH");
  return JSON.parse(patch[1].body);
}

beforeEach(() => {
  calls = [];
  apiFetch.mockReset();
  apiFetch.mockImplementation(apiFetchListing([]));
  globalThis.fetch = vi.fn(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return ok([]);
  });
});

async function mountedHook() {
  const { result } = renderHook(() => useScores());
  await waitFor(() => expect(calls).toEqual(expect.arrayContaining(["GET /scores", "GET /songs"])));
  calls = [];
  return result;
}

it("마운트하면 악보 목록을 토큰을 싣는 apiFetch로 불러야 한다", async () => {
  // Arrange & Act — the bare fetch sent no token, so the server could only
  // answer with every church's list.
  renderHook(() => useScores());
  await waitFor(() => expect(calls).toContain("GET /songs"));

  // Assert
  const listRequests = apiFetch.mock.calls.filter(([url, options]) =>
    isScoreListRequest(url, options)
  );
  expect(listRequests.map(([url]) => url)).toEqual([API_PATHS.scores]);
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it("수정한 뒤 목록을 다시 부를 때도 apiFetch를 써야 한다", async () => {
  // Arrange
  const result = await mountedHook();

  // Act
  await act(async () => {
    await result.current.updateScore({ scoreId: "score-1", title: "새 제목" });
  });

  // Assert
  expect(calls).toEqual(["PATCH /scores/score-1", "GET /scores"]);
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it("삭제한 뒤 목록을 다시 부를 때도 apiFetch를 써야 한다", async () => {
  // Arrange
  const result = await mountedHook();
  vi.spyOn(window, "confirm").mockReturnValue(true);

  // Act
  await act(async () => {
    await result.current.deleteScore("score-1");
  });

  // Assert
  expect(calls).toEqual(["DELETE /scores/score-1", "GET /scores"]);
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

it("파일 없이 수정하면 업로드 주소를 요청하지 않아야 한다", async () => {
  // Arrange
  const result = await mountedHook();

  // Act
  await act(async () => {
    await result.current.updateScore({ scoreId: "score-1", title: "새 제목" });
  });

  // Assert
  expect(calls.filter((call) => call.includes("/file"))).toEqual([]);
  expect(calls[0]).toBe("PATCH /scores/score-1");
  // The body must not carry file_uri at all: null would blank the column.
  expect(patchBody()).toEqual({ title: "새 제목" });
});

it("파일을 바꾸면 서명·업로드·PATCH 순서로 호출해야 한다", async () => {
  // Arrange
  const result = await mountedHook();

  // Act
  await act(async () => {
    await result.current.updateScore({ scoreId: "score-1", title: "은혜", file: IMAGE() });
  });

  // Assert
  expect(calls.slice(0, 3)).toEqual([
    "POST /scores/score-1/file",
    `PUT ${SIGNED.upload_url}`,
    "PATCH /scores/score-1",
  ]);
  expect(patchBody()).toEqual({ title: "은혜", file_uri: SIGNED.s3_key });
});

it("S3 업로드가 실패하면 악보를 새 파일로 옮기지 않아야 한다", async () => {
  // Arrange — the bucket refuses the PUT; the row must keep its current file.
  const result = await mountedHook();
  globalThis.fetch = vi.fn(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return { ok: false, json: async () => ({}) };
  });

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.updateScore({
      scoreId: "score-1",
      title: "은혜",
      file: IMAGE(),
    });
  });

  // Assert — the message rides back on the result as well as landing in
  // `error`, because the dialog's backdrop covers the page's alert.
  expect(outcome).toEqual({ ok: false, message: "S3 업로드에 실패했습니다." });
  expect(calls.some((call) => call.startsWith("PATCH"))).toBe(false);
  await waitFor(() => expect(result.current.error).toBe("S3 업로드에 실패했습니다."));
});

it("서명 발급이 실패하면 업로드를 시도하지 않아야 한다", async () => {
  // Arrange
  const result = await mountedHook();
  apiFetch.mockImplementation(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    if (String(url).endsWith("/file")) return { ok: false, json: async () => ({}) };
    return ok({});
  });

  // Act
  await act(async () => {
    await result.current.updateScore({ scoreId: "score-1", title: "은혜", file: IMAGE() });
  });

  // Assert
  expect(calls).toEqual(["POST /scores/score-1/file"]);
});

it("로그인 상태면 마운트할 때 보관함 목록도 불러야 한다", async () => {
  // Arrange & Act — the library tab and the upload dialog both draw this list.
  renderHook(() => useScores());
  await waitFor(() => expect(calls).toContain("GET /songs"));

  // Assert
  expect(calls.some((call) => call.includes("/scores"))).toBe(true);
});

it("scores에 song_id가 있으면 곡 수를 distinct song_id로 세어야 한다", async () => {
  // Arrange — 5 usages over 2 songs: the home page's "총 곡 수" must say 2,
  // not 5. That mistake is the bug this feature exists to fix.
  const items = [
    { id: "u1", song_id: "s1", title: "A" },
    { id: "u2", song_id: "s1", title: "A" },
    { id: "u3", song_id: "s1", title: "A" },
    { id: "u4", song_id: "s2", title: "B" },
    { id: "u5", song_id: "s2", title: "B" },
  ];
  apiFetch.mockImplementation(apiFetchListing(items));

  // Act
  const { result } = renderHook(() => useScores());

  // Assert
  await waitFor(() => expect(result.current.scores.length).toBe(5));
  expect(result.current.totalSongs).toBe(2);
});

it("song_id가 없는 항목은 title로 곡 수를 세어야 한다", async () => {
  // Arrange — a frontend deployed ahead of the migration sees no song_id;
  // the fallback must count titles rather than show 0.
  const items = [
    { id: "u1", song_id: "s1", title: "A" },
    { id: "u2", title: "B" },
    { id: "u3", title: "B" },
    { id: "u4", title: "C" },
  ];
  apiFetch.mockImplementation(apiFetchListing(items));

  // Act
  const { result } = renderHook(() => useScores());

  // Assert — {s1, B, C}
  await waitFor(() => expect(result.current.scores.length).toBe(4));
  expect(result.current.totalSongs).toBe(3);
});

it("업로드 409의 서버 detail을 메시지로 올려야 한다", async () => {
  // Arrange — the title is already in the library. The Korean detail must
  // reach the caller instead of being flattened to the generic failure message.
  const result = await mountedHook();
  apiFetch.mockImplementation(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return {
      ok: false,
      status: 409,
      json: async () => ({ detail: "이미 보관함에 있는 곡입니다. 보관함에서 골라 배치해 주세요." }),
    };
  });

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.uploadSong({ title: "은혜", file: IMAGE() });
  });

  // Assert
  expect(outcome).toEqual({
    ok: false,
    message: "이미 보관함에 있는 곡입니다. 보관함에서 골라 배치해 주세요.",
  });
  expect(calls.some((call) => call.startsWith("PUT"))).toBe(false);
});

it("제목 충돌 409의 서버 detail을 수정 실패 메시지로 올려야 한다", async () => {
  // Arrange — D8: the rename collision message is server-authored; the dialog
  // renders result.message, so flattening it here hides the reason on screen.
  const result = await mountedHook();
  apiFetch.mockImplementation(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return {
      ok: false,
      status: 409,
      json: async () => ({ detail: "같은 제목의 곡이 이미 있습니다." }),
    };
  });

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.updateScore({ scoreId: "score-1", title: "겹치는 제목" });
  });

  // Assert
  expect(outcome).toEqual({ ok: false, message: "같은 제목의 곡이 이미 있습니다." });
});

it("등록 422의 배열 detail을 읽을 수 있는 문장으로 올려야 한다", async () => {
  // Arrange — FastAPI's `detail` is a string for HTTPException but an array of
  // items for a 422, and Error(array) renders "[object Object]" in the dialog's
  // alert. uploadSong has no client-side length guard (updateScore
  // does), so an over-long title is exactly how a real user reaches this.
  const result = await mountedHook();
  apiFetch.mockImplementation(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return {
      ok: false,
      status: 422,
      json: async () => ({
        detail: [
          {
            type: "string_too_long",
            loc: ["body", "title"],
            msg: "String should have at most 255 characters",
            ctx: { max_length: 255 },
          },
        ],
      }),
    };
  });

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.uploadSong({ title: "가".repeat(256), file: IMAGE() });
  });

  // Assert — the field is labelled because the dialog shows nothing inline
  expect(outcome).toEqual({
    ok: false,
    message: "제목: 최대 255자까지 입력할 수 있습니다.",
  });
  expect(calls.some((call) => call.startsWith("PUT"))).toBe(false);
});

it("제목이 255자를 넘으면 아무 요청도 보내지 않아야 한다", async () => {
  // Arrange — the column is varchar(255); the server's 422 body is not readable.
  const result = await mountedHook();

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.updateScore({ scoreId: "score-1", title: "가".repeat(256) });
  });

  // Assert
  expect(outcome).toEqual({ ok: false, message: "제목은 255자 이내로 입력해주세요." });
  expect(calls).toEqual([]);
});

it("보관함 적용 409의 서버 detail을 메시지로 올려야 한다", async () => {
  // Arrange — the song is already on that week. The generic failure text told
  // the leader nothing they could act on; the detail names the week clash.
  const result = await mountedHook();
  apiFetch.mockImplementation(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return {
      ok: false,
      status: 409,
      json: async () => ({ detail: "이 곡은 이미 그 주차에 등록되어 있습니다." }),
    };
  });

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.placeSongOnWeek({
      songId: "song-1",
      weekOf: "2026-10-04",
    });
  });

  // Assert
  expect(outcome).toEqual({ ok: false, message: "이 곡은 이미 그 주차에 등록되어 있습니다." });
});

it("배치는 곡의 usages로 보내고 악보 목록과 보관함을 다시 불러야 한다", async () => {
  // Arrange
  const result = await mountedHook();

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.placeSongOnWeek({ songId: "song-1", weekOf: "2026-10-04" });
  });

  // Assert
  expect(outcome).toEqual({ ok: true });
  expect(calls[0]).toBe("POST /songs/song-1/usages");
  expect(calls).toEqual(expect.arrayContaining(["GET /scores", "GET /songs"]));
});

it("보관함 업로드는 곡만 만들고 받은 주소로 파일을 올려야 한다", async () => {
  // Arrange
  const result = await mountedHook();
  apiFetch.mockImplementation(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    if ((options.method ?? "GET") === "POST") {
      return ok({ song_id: "song-9", upload_url: "https://s3.example.com/put?sig=9" });
    }
    return ok([]);
  });

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.uploadSong({ title: "새 곡", file: IMAGE() });
  });

  // Assert
  expect(outcome).toEqual({ ok: true, songId: "song-9" });
  expect(calls.slice(0, 2)).toEqual(["POST /songs", "PUT https://s3.example.com/put?sig=9"]);
});

// --- reorderWeek: the home card's drag ------------------------------------

const WEEK_OF = "2026-11-22";
const LISTED = [
  { id: "u1", song_id: "s1", title: "A", week_of: WEEK_OF },
  { id: "u2", song_id: "s2", title: "B", week_of: WEEK_OF },
];
const MISMATCH = "그 주차의 곡 전체를 한 번씩 보내야 합니다.";
const SAVED_NOT_REREAD = "순서는 저장했지만 목록을 다시 불러오지 못했습니다.";

const isOrderPatch = (url, options = {}) =>
  String(url) === API_PATHS.weekContiOrder(WEEK_OF) && options.method === "PATCH";

/** apiFetch with the order PATCH and the score list answered by the test. */
function apiFetchReorder({ patch, listing = async () => ok(LISTED) }) {
  return async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    if (isOrderPatch(url, options)) return patch();
    if (isScoreListRequest(url, options)) return listing();
    return ok([]);
  };
}

async function mountedWithList() {
  apiFetch.mockImplementation(apiFetchListing(LISTED));
  const result = await mountedHook();
  await waitFor(() => expect(result.current.scores).toEqual(LISTED));
  return result;
}

// AC-21
it("순서 저장은 주차 순서 PATCH 를 score_id 만 실어 보내고 목록을 다시 불러야 한다", async () => {
  // Arrange
  const result = await mountedWithList();
  apiFetch.mockImplementation(apiFetchReorder({ patch: async () => ok({ pages: [] }) }));

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.reorderWeek({ weekOf: WEEK_OF, scoreIds: ["u2", "u1"] });
  });

  // Assert — PATCH first, then the re-read
  expect(outcome).toEqual({ ok: true, saved: true });
  expect(calls).toHaveLength(2);
  expect(calls[0].startsWith("PATCH ")).toBe(true);
  expect(calls[1]).toBe("GET /scores");
  const [url, options] = apiFetch.mock.calls.find(([, init]) => init?.method === "PATCH");
  expect(url).toBe(API_PATHS.weekContiOrder(WEEK_OF));
  expect(options.headers).toEqual({ "Content-Type": "application/json" });
  const body = JSON.parse(options.body);
  expect(body).toEqual({ items: [{ score_id: "u2" }, { score_id: "u1" }] });
  body.items.forEach((item) => expect(Object.keys(item)).toEqual(["score_id"]));
  expect(globalThis.fetch).not.toHaveBeenCalled();
});

// AC-21
it("순서 저장과 재조회가 되면 새 목록으로 바꾸고 오류를 지워야 한다", async () => {
  // Arrange
  const result = await mountedWithList();
  const reread = [LISTED[1], LISTED[0]];
  apiFetch.mockImplementation(
    apiFetchReorder({ patch: async () => ok({ pages: [] }), listing: async () => ok(reread) })
  );

  // Act
  await act(async () => {
    await result.current.reorderWeek({ weekOf: WEEK_OF, scoreIds: ["u2", "u1"] });
  });

  // Assert
  expect(result.current.scores).toEqual(reread);
  expect(result.current.error).toBe("");
});

// AC-22
it("순서 저장이 거절되면 목록을 다시 읽고 서버 detail 을 오류로 남겨야 한다", async () => {
  // Arrange — another device added a song, so the set no longer matches
  const result = await mountedWithList();
  apiFetch.mockImplementation(
    apiFetchReorder({
      patch: async () => ({ ok: false, status: 400, json: async () => ({ detail: MISMATCH }) }),
    })
  );

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.reorderWeek({ weekOf: WEEK_OF, scoreIds: ["u2", "u1"] });
  });

  // Assert — the re-read's own setError("") must not wipe the reason
  expect(outcome).toEqual({ ok: false, saved: false, message: MISMATCH });
  expect(calls[0].startsWith("PATCH ")).toBe(true);
  expect(calls).toContain("GET /scores");
  await waitFor(() => expect(result.current.error).toBe(MISMATCH));
});

// AC-22
it("순서 저장 요청이 네트워크에서 끊기면 저장 실패로 알리고 목록을 다시 읽어야 한다", async () => {
  // Arrange
  const result = await mountedWithList();
  apiFetch.mockImplementation(
    apiFetchReorder({
      patch: async () => {
        throw new TypeError("Failed to fetch");
      },
    })
  );

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.reorderWeek({ weekOf: WEEK_OF, scoreIds: ["u2", "u1"] });
  });

  // Assert
  expect(outcome).toEqual({ ok: false, saved: false, message: "순서를 저장하지 못했습니다." });
  expect(calls).toContain("GET /scores");
  await waitFor(() => expect(result.current.error).toBe("순서를 저장하지 못했습니다."));
});

// AC-27
it("순서는 저장됐는데 재조회가 실패하면 saved 로 알리고 이전 목록을 지켜야 한다", async () => {
  // Arrange
  const result = await mountedWithList();
  apiFetch.mockImplementation(
    apiFetchReorder({
      patch: async () => ok({ pages: [] }),
      listing: async () => ({ ok: false, status: 500, json: async () => ({}) }),
    })
  );

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.reorderWeek({ weekOf: WEEK_OF, scoreIds: ["u2", "u1"] });
  });

  // Assert — not "ok": the list on screen is the old one
  expect(outcome).toEqual({ ok: false, saved: true, message: SAVED_NOT_REREAD });
  await waitFor(() => expect(result.current.error).toBe(SAVED_NOT_REREAD));
  expect(result.current.scores).toEqual(LISTED);
});

// AC-23
it.each([
  ["성공", { patch: async () => ok({ pages: [] }) }],
  [
    "거절",
    {
      patch: async () => ({ ok: false, status: 400, json: async () => ({ detail: MISMATCH }) }),
    },
  ],
  [
    "재조회 실패",
    {
      patch: async () => ok({ pages: [] }),
      listing: async () => ({ ok: false, status: 500, json: async () => ({}) }),
    },
  ],
])("순서 저장 중에는 isReordering 이 참이고 끝나면(%s) 거짓이어야 한다", async (_, answers) => {
  // Arrange — the PATCH is held open until the test lets it go
  const result = await mountedWithList();
  expect(result.current.isReordering).toBe(false);
  let release;
  const gate = new Promise((settle) => {
    release = settle;
  });
  apiFetch.mockImplementation(
    apiFetchReorder({
      ...answers,
      patch: async () => {
        await gate;
        return answers.patch();
      },
    })
  );

  // Act
  let running;
  act(() => {
    running = result.current.reorderWeek({ weekOf: WEEK_OF, scoreIds: ["u2", "u1"] });
  });

  // Assert
  await waitFor(() => expect(result.current.isReordering).toBe(true));
  await act(async () => {
    release();
    await running;
  });
  expect(result.current.isReordering).toBe(false);
});
