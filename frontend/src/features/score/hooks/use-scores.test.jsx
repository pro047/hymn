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
import { useScores } from "./use-scores";

vi.mock("../../../api/client", () => ({ apiFetch: vi.fn() }));
vi.mock("../../../lib/auth-storage", () => ({ isAuthenticated: () => true }));

const ok = (body) => ({ ok: true, json: async () => body });

const SIGNED = { upload_url: "https://s3.example.com/put?sig=1", s3_key: "scores/c1/new.png" };
const IMAGE = () => new File(["x"], "rescan.png", { type: "image/png" });

/** Records every call as "METHOD path" so order can be asserted in one array. */
let calls;

function trace(method, url) {
  calls.push(`${method} ${String(url).replace(/^.*?(?=\/scores|https:)/, "")}`);
}

beforeEach(() => {
  calls = [];
  apiFetch.mockReset();
  apiFetch.mockImplementation(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    if (String(url).endsWith("/file")) return ok(SIGNED);
    // The mount fetches the saved-score list through apiFetch too, and the hook
    // maps over whatever comes back.
    if (String(url).includes("saved-scores")) return ok([]);
    return ok({ id: "score-1" });
  });
  globalThis.fetch = vi.fn(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return ok([]);
  });
});

async function mountedHook() {
  const { result } = renderHook(() => useScores());
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
  calls = [];
  return result;
}

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
  expect(JSON.parse(apiFetch.mock.calls.at(-1)[1].body)).toEqual({ title: "새 제목" });
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
  const patchBody = JSON.parse(apiFetch.mock.calls.at(-1)[1].body);
  expect(patchBody).toEqual({ title: "은혜", file_uri: SIGNED.s3_key });
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

it("보관함 플래그가 꺼져 있으면 저장소 목록을 부르지 않아야 한다", async () => {
  // Arrange & Act — SAVED_SCORES_ENABLED is false, so nothing renders saved
  // scores; fetching them cost a round trip per mount and discarded the answer.
  renderHook(() => useScores());
  await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());

  // Assert
  expect(calls.some((call) => call.includes("saved-scores"))).toBe(false);
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
  globalThis.fetch = vi.fn(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return ok(items);
  });

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
  globalThis.fetch = vi.fn(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return ok(items);
  });

  // Act
  const { result } = renderHook(() => useScores());

  // Assert — {s1, B, C}
  await waitFor(() => expect(result.current.scores.length).toBe(4));
  expect(result.current.totalSongs).toBe(3);
});

it("재사용 응답이면 S3 PUT 없이 성공과 reused를 돌려줘야 한다", async () => {
  // Arrange — upload_url is null on a reused create; running the PUT anyway
  // would be fetch(null) and a crash. This lives here and not in the dialog
  // test: the dialog mocks onUploadSubmit, so a PUT assertion there would
  // pass no matter what the hook does.
  const result = await mountedHook();
  apiFetch.mockImplementation(async (url, options = {}) => {
    trace(options.method ?? "GET", url);
    return ok({ score_id: "score-9", upload_url: null, reused_song: true });
  });

  // Act
  let outcome;
  await act(async () => {
    outcome = await result.current.createScoreWithUpload({
      title: "은혜",
      weekOf: "2026-08-30",
      file: IMAGE(),
    });
  });

  // Assert — no PUT anywhere, but the list still refreshes: it was a success
  expect(outcome).toEqual({ ok: true, scoreId: "score-9", reused: true });
  expect(calls.some((call) => call.startsWith("PUT"))).toBe(false);
  expect(calls.some((call) => call.startsWith("GET") && call.includes("/scores"))).toBe(true);
});

it("악보 등록 409의 서버 detail을 메시지로 올려야 한다", async () => {
  // Arrange — D5-a: same song, same week. The Korean detail must reach the
  // caller instead of being flattened to the generic failure message.
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
    outcome = await result.current.createScoreWithUpload({
      title: "은혜",
      weekOf: "2026-08-30",
      file: IMAGE(),
    });
  });

  // Assert
  expect(outcome).toEqual({ ok: false, message: "이 곡은 이미 그 주차에 등록되어 있습니다." });
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
  // alert. createScoreWithUpload has no client-side length guard (updateScore
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
    outcome = await result.current.createScoreWithUpload({
      title: "가".repeat(256),
      weekOf: "2026-08-30",
      file: IMAGE(),
    });
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
