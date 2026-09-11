/**
 * @vitest-environment jsdom
 * @vitest-environment-options { "resources": "usable" }
 *
 * The sheet editor, end to end through the page: the conti screen, the hook
 * that talks to the server, and a real fabric canvas underneath.
 *
 * `resources: usable` is set here and nowhere else. fabric cannot open a sheet
 * it could not load, and jsdom refuses to fetch images without it — but the
 * option also lets jsdom reach the network, so every URL in this file is a
 * data: URL and the flag stays scoped to this one file.
 *
 * The assertions pin the *request* the editor makes, not the pixels it draws.
 * jsdom cannot judge a picture (the scissors of 2026-09-09 rendered fine and
 * was invisible on screen), but it can say exactly which three calls a save
 * makes, in which order, and what goes in the body — which is where this
 * feature can leak a key or store an expiring URL.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import ContiPage from "./conti-page";

// A real 120x170 png. Portrait on purpose: every score in production is, and
// a landscape stand-in cannot tell "fit the whole sheet" apart from "fit the
// width" — the two agree on a wide image and disagree on a tall one, which is
// exactly the bug this file failed to catch the first time.
const SHEET_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAHgAAACqCAIAAADp8ByhAAABh0lEQVR4nO3QQQ0AIBDAMMC/Ye6FCvZqDSzZnrmL/07QwOiO0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmJ0xOiI0RGjI0ZHjI4YHTE6YnTE6IjREaMjRkeMjhgdMTpidMToiNERoyNGR4yOGB0xOmL0ajyxCgRBKhPUbwAAAABJRU5ErkJggg==";

const WITH_FILE = {
  score_id: "a",
  title: "은혜",
  starts_new_page: false,
  image_url: SHEET_PNG,
};
const WITHOUT_FILE = {
  score_id: "b",
  title: "믿음",
  starts_new_page: false,
  image_url: null,
};

const CONTI = { week_of: "2026-09-13", slot_ratio: 0.75, pages: [[WITH_FILE, WITHOUT_FILE]] };

// One text object standing in for "somebody already marked this sheet". Its
// text is what the save has to hand back untouched for the round trip to mean
// anything.
const SEEDED_DOC = {
  version: "6.0.0",
  objects: [{ type: "IText", text: "3부", left: 10, top: 12, fontSize: 24, fill: "#dc2626" }],
};

const SIGNED = {
  upload_url: "https://s3.test/put?sig=abc",
  s3_key: "scores/church-1/edited-1.png",
};

function replyOf(reply) {
  const status = reply.status ?? 200;
  return Promise.resolve({
    ok: status < 400,
    status,
    headers: new Headers(),
    json: async () => reply.body ?? {},
    blob: async () => new Blob([]),
  });
}

/**
 * Routes by URL and method. Returns the call log, which is what most of these
 * tests assert on — the order of the three calls a save makes is the property
 * that keeps a failed upload from pointing a week at an object that does not
 * exist.
 */
function mockApi({
  conti = { body: CONTI },
  edit = { body: { edited_file_uri: null, edit_doc: null, source_image_url: SHEET_PNG } },
  signed = { body: SIGNED },
  upload = {},
  save = { body: {} },
  remove = { body: {} },
} = {}) {
  const calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input, init = {}) => {
      const url = String(input);
      const method = init.method ?? "GET";
      calls.push({
        url,
        method,
        // The S3 PUT carries a Blob, not JSON; recording its size is enough to
        // show a sheet was actually uploaded.
        body:
          typeof init.body === "string"
            ? JSON.parse(init.body)
            : init.body
              ? { blobSize: init.body.size, blobType: init.body.type }
              : null,
        // Kept whole as well, so a test can read the png's own header rather
        // than trust what the app said it uploaded.
        blob: typeof init.body === "string" ? null : (init.body ?? null),
      });

      let reply;
      if (url.startsWith("https://s3.test/")) reply = upload;
      else if (url.endsWith("/edited-file")) reply = signed;
      else if (url.endsWith("/edit")) {
        reply = method === "GET" ? edit : method === "DELETE" ? remove : save;
      } else reply = conti;

      if (reply.pending) return new Promise(() => {});
      return replyOf(reply);
    })
  );
  return calls;
}

const renderConti = () =>
  render(
    <MemoryRouter initialEntries={["/conti/2026-09-13"]}>
      <Routes>
        <Route path="/conti/:week" element={<ContiPage />} />
      </Routes>
    </MemoryRouter>
  );

/** Opens the editor and waits until fabric has the sheet on screen — every
 * control is disabled until then, so clicking earlier does nothing. */
async function openEditor(title = "은혜") {
  fireEvent.click(await screen.findByRole("button", { name: `${title} 편집` }));
  await waitFor(() => expect(screen.getByRole("button", { name: "저장" }).disabled).toBe(false));
}

/** A png's declared size, read out of its IHDR chunk.
 *
 * Bytes 16..23 of every png are width then height, big-endian. Decoding the
 * image would need a canvas; this needs only the header, and it answers the
 * one question the zoom can get wrong.
 */
async function sizeOfPng(blob) {
  const header = new DataView(await blob.arrayBuffer());
  return { width: header.getUint32(16), height: header.getUint32(20) };
}

const callsTo = (calls, suffix, method) =>
  calls.filter((call) => call.url.endsWith(suffix) && (!method || call.method === method));

beforeEach(() => {
  mockApi();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("편집 열기", () => {
  it("악보 파일이 있는 곡에만 편집 버튼이 있어야 한다", async () => {
    renderConti();

    expect(await screen.findByRole("button", { name: "은혜 편집" })).toBeTruthy();
    // A sheet with no file has nothing to draw on, and the editor would open
    // onto an empty canvas.
    expect(screen.queryByRole("button", { name: "믿음 편집" })).toBeNull();
  });

  it("편집을 열면 그 곡의 편집 상태를 읽어야 한다", async () => {
    const calls = mockApi();
    renderConti();

    await openEditor();

    expect(callsTo(calls, "/scores/a/edit", "GET")).toHaveLength(1);
  });

  it("이미 저장된 편집이 있으면 캔버스에 되살려야 한다", async () => {
    // The round trip that makes storing a document worth anything: what was
    // drawn before comes back as an object that can be moved and deleted,
    // rather than as pixels baked into the sheet.
    const calls = mockApi({
      edit: {
        body: {
          edited_file_uri: "scores/church-1/old.png",
          edit_doc: SEEDED_DOC,
          source_image_url: SHEET_PNG,
        },
      },
    });
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(callsTo(calls, "/scores/a/edit", "PUT")).toHaveLength(1));
    const saved = callsTo(calls, "/scores/a/edit", "PUT")[0].body;
    expect(saved.edit_doc.objects).toHaveLength(1);
    expect(saved.edit_doc.objects[0].text).toBe("3부");
  });
});

describe("저장", () => {
  it("서명, 업로드, 기록 순서로 세 번 요청해야 한다", async () => {
    // Order is the property, not the count. Recording first would point the
    // week at an object that was never written, and the sheet would draw as a
    // broken image rather than as the one it already had.
    const calls = mockApi();
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(callsTo(calls, "/scores/a/edit", "PUT")).toHaveLength(1));
    const saveSequence = calls
      .filter(
        (call) =>
          call.url.endsWith("/edited-file") ||
          call.url.startsWith("https://s3.test/") ||
          (call.url.endsWith("/scores/a/edit") && call.method === "PUT")
      )
      // VITE_API_BASE_URL is unset under vitest, so the app's own URLs are
      // prefixed with "undefined". The path is what this test is about.
      .map(
        (call) =>
          `${call.method} ${call.url.replace(/\?.*/, "").replace(/^.*?(?=\/scores\/|https:)/, "")}`
      );
    expect(saveSequence).toEqual([
      "POST /scores/a/edited-file",
      "PUT https://s3.test/put",
      "PUT /scores/a/edit",
    ]);
  });

  it("서명이 준 키를 그대로 기록해야 한다", async () => {
    const calls = mockApi();
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(callsTo(calls, "/scores/a/edit", "PUT")).toHaveLength(1));
    expect(callsTo(calls, "/scores/a/edit", "PUT")[0].body.edited_file_uri).toBe(SIGNED.s3_key);
  });

  it("평탄화한 png 를 업로드해야 한다", async () => {
    const calls = mockApi();
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(callsTo(calls, "/scores/a/edit", "PUT")).toHaveLength(1));
    const uploaded = calls.find((call) => call.url.startsWith("https://s3.test/"));
    expect(uploaded.body.blobType).toBe("image/png");
    // Not an empty body: an upload of zero bytes would still get a 200 from
    // this stub and leave the week pointing at nothing.
    expect(uploaded.body.blobSize).toBeGreaterThan(0);
  });

  it("저장하는 문서에 배경 이미지를 담지 않아야 한다", async () => {
    // fabric puts the background's `src` in toJSON, and that src is a
    // presigned URL — fifteen minutes of credential written into a row that
    // outlives it, and a sheet that reopens to a broken background after it
    // expires. The server hands back a fresh one on every open instead.
    const calls = mockApi();
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(callsTo(calls, "/scores/a/edit", "PUT")).toHaveLength(1));
    const doc = callsTo(calls, "/scores/a/edit", "PUT")[0].body.edit_doc;
    expect(doc.backgroundImage).toBeUndefined();
    expect(JSON.stringify(doc)).not.toContain("data:image/png");
  });

  it("업로드가 실패하면 편집본을 기록하지 않아야 한다", async () => {
    // The half-done state this ordering exists to prevent.
    const calls = mockApi({ upload: { status: 403 } });
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await screen.findByRole("alert");
    expect(callsTo(calls, "/scores/a/edit", "PUT")).toHaveLength(0);
  });

  it("저장에 성공하면 콘티를 다시 읽어야 한다", async () => {
    // The preview draws image_url off the conti response, so without this the
    // sheet on screen stays the one from before the edit and the save looks
    // like it did nothing.
    const calls = mockApi();
    renderConti();
    await openEditor();
    const contiReadsBefore = callsTo(calls, "/conti", "GET").length;

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(callsTo(calls, "/conti", "GET").length).toBe(contiReadsBefore + 1));
  });

  it("저장에 실패하면 편집기를 닫지 않아야 한다", async () => {
    // Closing on failure would throw the drawing away with nothing saved.
    mockApi({ save: { status: 500, body: { detail: "저장 실패" } } });
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "저장" })).toBeTruthy();
  });
});

describe("원본으로 되돌리기", () => {
  it("편집한 적이 없으면 되돌리기를 제안하지 않아야 한다", async () => {
    renderConti();
    await openEditor();

    expect(screen.queryByRole("button", { name: "원본으로 되돌리기" })).toBeNull();
  });

  it("확인을 거친 뒤에 편집을 지워야 한다", async () => {
    // Two steps on purpose: this throws away work that cannot be recovered.
    const calls = mockApi({
      edit: {
        body: {
          edited_file_uri: "scores/church-1/old.png",
          edit_doc: SEEDED_DOC,
          source_image_url: SHEET_PNG,
        },
      },
    });
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "원본으로 되돌리기" }));
    expect(callsTo(calls, "/scores/a/edit", "DELETE")).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "지우기" }));

    await waitFor(() => expect(callsTo(calls, "/scores/a/edit", "DELETE")).toHaveLength(1));
  });
});

describe("보기 크기", () => {
  /** jsdom lays nothing out, so clientWidth is 0 on every element and the hook
   * would fall back to its stand-in box. Giving the box a size is what makes
   * "does the sheet fit it" a question with an answer here.
   *
   * Element.prototype, not HTMLElement's: that is where jsdom defines these,
   * and restoring a descriptor read off the wrong prototype throws. */
  function withBox(width, height) {
    const original = {
      width: Object.getOwnPropertyDescriptor(Element.prototype, "clientWidth"),
      height: Object.getOwnPropertyDescriptor(Element.prototype, "clientHeight"),
    };
    Object.defineProperty(Element.prototype, "clientWidth", {
      configurable: true,
      get: () => width,
    });
    Object.defineProperty(Element.prototype, "clientHeight", {
      configurable: true,
      get: () => height,
    });
    return () => {
      Object.defineProperty(Element.prototype, "clientWidth", original.width);
      Object.defineProperty(Element.prototype, "clientHeight", original.height);
    };
  }

  const drawnSize = () => {
    // The lower canvas is the one fabric sizes; the upper one mirrors it.
    const canvas = document.querySelector("canvas");
    return { width: canvas.width, height: canvas.height };
  };

  it("악보 전체가 편집 상자 안에 들어가야 한다", async () => {
    // The bug this replaces: the sheet was drawn at a fixed 900px wide
    // whatever the box was, so a portrait score opened several screens tall
    // and there was no way to reach the rest of it.
    const restore = withBox(800, 600);
    try {
      renderConti();
      await openEditor();

      const { width, height } = drawnSize();
      expect(width).toBeLessThanOrEqual(800);
      expect(height).toBeLessThanOrEqual(600);
      // And not shrunk to nothing: "fits" has to mean it fills what it can.
      expect(width === 800 || height === 600).toBe(true);
    } finally {
      restore();
    }
  });

  it("확대하면 커지고 맞춤을 누르면 되돌아와야 한다", async () => {
    const restore = withBox(800, 600);
    try {
      renderConti();
      await openEditor();
      const fitted = drawnSize();

      fireEvent.click(screen.getByRole("button", { name: "확대" }));
      const enlarged = drawnSize();
      expect(enlarged.width).toBeGreaterThan(fitted.width);

      fireEvent.click(screen.getByRole("button", { name: "맞춤" }));
      expect(drawnSize()).toEqual(fitted);
    } finally {
      restore();
    }
  });

  it("맞춤 상태에서는 더 축소할 수 없어야 한다", async () => {
    // Smaller than the whole sheet is not a view anyone asked for, and it is
    // the state the button would otherwise strand a leader in.
    renderConti();
    await openEditor();

    expect(screen.getByRole("button", { name: "축소" }).disabled).toBe(true);
  });

  it("확대해도 저장본은 악보 자체 해상도여야 한다", async () => {
    // The zoom is a view, not a resampling. Saving what the screen shows
    // would write an interpolated sheet over the original.
    const restore = withBox(800, 600);
    try {
      const calls = mockApi();
      renderConti();
      await openEditor();
      fireEvent.click(screen.getByRole("button", { name: "확대" }));

      fireEvent.click(screen.getByRole("button", { name: "저장" }));
      await waitFor(() => expect(callsTo(calls, "/scores/a/edit", "PUT")).toHaveLength(1));

      const uploaded = calls.find((call) => call.url.startsWith("https://s3.test/"));
      const png = await sizeOfPng(uploaded.blob);
      expect(png).toEqual({ width: 120, height: 170 });
    } finally {
      restore();
    }
  });
});

describe("도구", () => {
  it("처음에는 그리기가 골라져 있어야 한다", async () => {
    // The tool a leader reaches for first, and the one that needs no second
    // click before it does anything.
    renderConti();
    await openEditor();

    expect(screen.getByRole("button", { name: "그리기" }).getAttribute("aria-pressed")).toBe(
      "true"
    );
  });

  it("도구를 바꿔도 캔버스를 다시 만들지 않아야 한다", async () => {
    // Rebuilding it would drop everything drawn so far. Observed through the
    // sheet: a reload would fetch source_image_url again.
    const calls = mockApi();
    renderConti();
    await openEditor();
    const editReadsBefore = callsTo(calls, "/scores/a/edit", "GET").length;

    fireEvent.click(screen.getByRole("button", { name: "글자" }));
    fireEvent.click(screen.getByRole("button", { name: "파랑" }));

    expect(screen.getByRole("button", { name: "글자" }).getAttribute("aria-pressed")).toBe("true");
    expect(callsTo(calls, "/scores/a/edit", "GET")).toHaveLength(editReadsBefore);
  });

  it("고른 것이 없으면 선택 지우기를 누를 수 없어야 한다", async () => {
    renderConti();
    await openEditor();

    expect(screen.getByRole("button", { name: "선택 지우기" }).disabled).toBe(true);
  });
});
