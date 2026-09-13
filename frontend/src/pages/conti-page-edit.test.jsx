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
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import ContiPage from "./conti-page";

/** The canvases the editor built, newest last.
 *
 * A click never reaches fabric under jsdom — pointer and mouse events on both
 * canvas elements leave the object count at zero (measured 2026-09-11) — so
 * the undo tests below could not draw anything to take back. Holding the
 * instance is the way past that: the test adds the object fabric itself would
 * have added, and everything after that point is the real thing.
 *
 * This is real fabric, subclassed, not a stand-in: loadFromJSON runs, every
 * event fires, and the existing tests in this file go through the same class
 * unchanged. What it does NOT cover is the step it replaces — whether a
 * click, a drag or a keystroke reaches fabric at all. That stays on the
 * 눈 확인 list.
 */
const canvases = [];

/** Set to a promise to hold every loadFromJSON until it settles.
 *
 * Undo awaits that call, and in this file it resolves almost immediately —
 * the documents hold only paths and labels, so nothing is fetched. That
 * leaves no window for a second press to land inside the first, which is the
 * one thing the re-entry guard exists for. Holding the call open is how the
 * window is made wide enough to aim at.
 */
let holdLoad = null;

vi.mock("fabric", async (importOriginal) => {
  const actual = await importOriginal();
  class ReachableCanvas extends actual.Canvas {
    constructor(...args) {
      super(...args);
      canvases.push(this);
    }

    async loadFromJSON(...args) {
      if (holdLoad) await holdLoad;
      return super.loadFromJSON(...args);
    }
  }
  return { ...actual, Canvas: ReachableCanvas };
});

/** The canvas currently on screen. */
const sheet = () => canvases[canvases.length - 1];

/** Draws the way the pencil does: one Path, added to the canvas.
 *
 * The brush is not driven here because what it produces is a Path either way —
 * and going through onMouseDown/Move/Up would test fabric's brush rather than
 * this app's history.
 */
async function drawStroke(y = 10) {
  const { Path } = await import("fabric");
  await act(async () => {
    sheet().add(
      new Path(`M 0 ${y} Q 10 ${y + 10} 20 ${y}`, {
        stroke: "#dc2626",
        fill: "",
        strokeWidth: 3,
      })
    );
  });
}

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

// The same 120x170 sheet with each quarter a different flat colour: top-left
// red, top-right green, bottom-left blue, bottom-right yellow.
//
// A size-only assertion cannot tell a whole sheet from a quarter of one blown
// up to the same dimensions, which is exactly the bug that got through — the
// background sat at left:0 top:0 while fabric 7 places objects by their
// centre, so three quarters of every sheet hung off the canvas and the export
// still measured 120x170. These colours make the difference readable.
const QUADRANT_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAHgAAACqCAIAAADp8ByhAAABlElEQVR4nO3dwQ3AMAzEMKf775xuwcKoOMFB8N/nzj5n4ejn6wF/UWik0EihkUIjhUYKjRQaKTRSaKTQSKGRQiOFRgqNFBopNFJopNBIoZFCI4VGCo0UGik0Umik0EihkUIjhUYKjRQaKTRSaKTQSKGRQiOFRgqNFBopNFJopNBIoZFCI4VGCo0UGik0Umik0EihkUIjhUYKjRQaKTRSaKTQSKGRQiOFRgqNFBopNFJopNBIoZFCI4VGCo0UGik0Umik0EihkUIjhUYKjRQaKTRSaKTQSKGRM7PvU+69Z7bpopFCI4VGCo0UGik0Umik0EihkUIjhUYKjRQaKTRSaKTQSKGRQiOFRgqNFBopNFJopNBIoZFCI4VGCo0UGik0Umik0EihkUIjhUYKjRQaKTRSaKTQSKGRQiOFRgqNFBopNFJopNBIoZFCI4VGCo0UGik0Umik0EihkUIjhUYKjRQaKTRSaKTQSKGRQiOFRgqNFBopNFJopNBIoZFCI4VGCo0UGik0Umik0EihkUIjhUYKPcYL6uQGUIPRpDYAAAAASUVORK5CYII=";

const QUADRANTS = [
  { name: "왼쪽 위", at: [0.25, 0.25], rgb: [255, 0, 0] },
  { name: "오른쪽 위", at: [0.75, 0.25], rgb: [0, 255, 0] },
  { name: "왼쪽 아래", at: [0.25, 0.75], rgb: [0, 0, 255] },
  { name: "오른쪽 아래", at: [0.75, 0.75], rgb: [255, 255, 0] },
];

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

/** The colours a png actually carries at four sample points.
 *
 * Decoded through a real canvas — node-canvas is installed for exactly this
 * kind of check (pnpm-workspace.yaml) — because the question here is what the
 * pixels are, and nothing short of decoding them answers it.
 */
async function quadrantColorsOf(blob) {
  const dataUrl = `data:image/png;base64,${btoa(
    String.fromCharCode(...new Uint8Array(await blob.arrayBuffer()))
  )}`;
  const image = new Image();
  await new Promise((resolve, reject) => {
    image.onload = resolve;
    image.onerror = reject;
    image.src = dataUrl;
  });
  const surface = document.createElement("canvas");
  surface.width = image.naturalWidth;
  surface.height = image.naturalHeight;
  const context = surface.getContext("2d");
  context.drawImage(image, 0, 0);
  return QUADRANTS.map((quadrant) => {
    const [fx, fy] = quadrant.at;
    const pixel = context.getImageData(
      Math.floor(image.naturalWidth * fx),
      Math.floor(image.naturalHeight * fy),
      1,
      1
    ).data;
    return { name: quadrant.name, rgb: [pixel[0], pixel[1], pixel[2]] };
  });
}

const callsTo = (calls, suffix, method) =>
  calls.filter((call) => call.url.endsWith(suffix) && (!method || call.method === method));

beforeEach(() => {
  canvases.length = 0;
  holdLoad = null;
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

  it("악보 전체를 저장해야 한다 — 일부만 담기지 않아야 한다", async () => {
    // The assertion the size-only ones could not make. Each quarter of the
    // source is a different colour, so a background hanging off the canvas
    // (fabric 7 places objects by their centre, not their corner) shows up
    // here as the wrong colour in three of the four samples — while the png's
    // dimensions stay exactly right.
    const calls = mockApi({
      edit: {
        body: { edited_file_uri: null, edit_doc: null, source_image_url: QUADRANT_PNG },
      },
    });
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(callsTo(calls, "/scores/a/edit", "PUT")).toHaveLength(1));

    const uploaded = calls.find((call) => call.url.startsWith("https://s3.test/"));
    expect(await quadrantColorsOf(uploaded.blob)).toEqual(
      QUADRANTS.map((quadrant) => ({ name: quadrant.name, rgb: quadrant.rgb }))
    );
  });

  it("이미지를 만들지 못하면 조용히 끝나지 않아야 한다", async () => {
    // toDataURL throws SecurityError on a canvas that has drawn an image
    // fetched without CORS. It used to propagate out of an async onClick as
    // an unhandled rejection: no message, no error state, nothing saved, and
    // a button that looked like it had done nothing at all.
    const calls = mockApi();
    renderConti();
    await openEditor();
    const original = HTMLCanvasElement.prototype.toDataURL;
    HTMLCanvasElement.prototype.toDataURL = () => {
      throw new Error("SecurityError");
    };

    try {
      fireEvent.click(screen.getByRole("button", { name: "저장" }));

      expect((await screen.findByRole("alert")).textContent).toContain("악보를 이미지로");
      expect(callsTo(calls, "/edited-file", "POST")).toHaveLength(0);
      // Still open, so the drawing is not thrown away with nothing saved.
      expect(screen.getByRole("button", { name: "저장" })).toBeTruthy();
    } finally {
      HTMLCanvasElement.prototype.toDataURL = original;
    }
  });

  it("서명 요청이 거절되면 서버가 준 이유를 보여야 한다", async () => {
    // A member editing somebody else's upload gets 403 from
    // _writable_score_or_error. A fixed "주소를 받지 못했습니다" would replace
    // the one sentence that explains what to do about it.
    mockApi({
      signed: {
        status: 403,
        body: { detail: "본인이 올린 악보만 수정하거나 삭제할 수 있습니다." },
      },
    });
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    expect((await screen.findByRole("alert")).textContent).toContain("본인이 올린 악보만");
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
    fireEvent.click(screen.getByRole("button", { name: "모두 지우기" }));

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

  /** A stand-in ResizeObserver that records a callback only once the box is
   * actually observed.
   *
   * Recording in the constructor instead would let a hook that builds an
   * observer and never points it at anything pass this file — which is what
   * the first version of these tests did.
   */
  const makeResizeObserver = (observers) =>
    class {
      constructor(callback) {
        this.callback = callback;
      }
      observe() {
        observers.push(this.callback);
      }
      disconnect() {}
    };

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

  it("상자를 나중에 재도 악보가 상자를 채워야 한다", async () => {
    /** jsdom ships no ResizeObserver, so the re-fit path has none to fire.
     * This stand-in records the callback and lets the test say "the box has
     * been laid out now" — which is the moment a real browser delivers and
     * the moment the first measurement can have been too early for. */
    const observers = [];
    vi.stubGlobal("ResizeObserver", makeResizeObserver(observers));
    // Opens with no measurable box at all — the fit falls back to a stand-in,
    // which is exactly the wrong answer this is here to correct.
    let restore = withBox(0, 0);
    try {
      renderConti();
      await openEditor();
      restore();
      restore = withBox(800, 600);

      await act(async () => {
        observers.forEach((callback) => callback());
      });

      const { width, height } = drawnSize();
      expect(width).toBeLessThanOrEqual(800);
      expect(height).toBeLessThanOrEqual(600);
      expect(width === 800 || height === 600).toBe(true);
    } finally {
      restore();
    }
  });

  it("상자 크기가 변해도 확대해둔 배율을 유지해야 한다", async () => {
    // A window resize should carry the sheet along, not undo the enlarging a
    // leader just did to write in a tight bar.
    const observers = [];
    vi.stubGlobal("ResizeObserver", makeResizeObserver(observers));
    const restore = withBox(800, 600);
    try {
      renderConti();
      await openEditor();
      fireEvent.click(screen.getByRole("button", { name: "확대" }));
      const enlarged = drawnSize();

      await act(async () => {
        observers.forEach((callback) => callback());
      });

      // Same box, so re-fitting at the same scale must land on the same size.
      expect(drawnSize()).toEqual(enlarged);
      // And not back at the fit, which is what dropping the scale would give.
      expect(screen.getByRole("button", { name: "축소" }).disabled).toBe(false);
    } finally {
      restore();
    }
  });

  it("상자가 커지면 배율 표시도 따라가야 한다", async () => {
    // The label was computed from a ref, so a re-fit that left the scale
    // alone changed nothing React could see: setScale(sameValue) bails out
    // and the percentage stayed on whatever the first measurement gave.
    const observers = [];
    vi.stubGlobal("ResizeObserver", makeResizeObserver(observers));
    let restore = withBox(400, 300);
    try {
      renderConti();
      await openEditor();
      const before = screen.getByText(/%$/).textContent;

      restore();
      restore = withBox(800, 600);
      await act(async () => {
        observers.forEach((callback) => callback());
      });

      const after = screen.getByText(/%$/).textContent;
      expect(after).not.toBe(before);
      // Twice the box, twice the fit — the sheet is height-limited either
      // way. Within one point, because the label is rounded and 176 doubled
      // is not the same as 352.94 rounded.
      expect(Math.abs(parseInt(after, 10) - parseInt(before, 10) * 2)).toBeLessThanOrEqual(1);
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
});

describe("지우기", () => {
  const eraseButton = () => screen.getByRole("button", { name: "지우기", exact: true });
  const undoButton = () => screen.getByRole("button", { name: "실행 취소" });

  /** Presses and releases the sheet through fabric's own pointer handling.
   *
   * Not a hand-fired event: fabric caches the target under the pointer before
   * any mouse event is fired and keeps using that cache for the rest of the
   * press, so what happens *after* the app's handler — selecting the object,
   * setting up a drag on it — is where the eraser can go wrong, and a fired
   * event skips all of it. A DOM mousedown never reaches fabric under jsdom
   * (measured 2026-09-11), so its handler is called directly with one.
   *
   * `at` is in the sheet's own coordinates; the viewport transform turns it
   * into where on the canvas element a pointer would be. fabric then reads the
   * event back through the element's offset, which under jsdom is not zero —
   * 16px on each axis (measured), enough to miss a short mark entirely — so
   * the offset is taken from fabric itself and cancelled out.
   */
  async function pressOn(target, at) {
    const { Point, util } = await import("fabric");
    const canvas = sheet();
    const scene = target ? target.getCenterPoint() : new Point(at.x, at.y);
    const view = util.transformPoint(scene, canvas.viewportTransform);
    const origin = canvas.getViewportPoint(new MouseEvent("mousedown", { clientX: 0, clientY: 0 }));
    const init = {
      clientX: view.x - origin.x,
      clientY: view.y - origin.y,
      button: 0,
      bubbles: true,
    };
    await act(async () => {
      canvas._onMouseDown(new MouseEvent("mousedown", init));
      canvas._onMouseUp(new MouseEvent("mouseup", init));
    });
  }

  it("지우기는 도구 하나여야 한다 — 선택 지우기 버튼은 없어야 한다", async () => {
    renderConti();
    await openEditor();

    fireEvent.click(eraseButton());

    expect(eraseButton().getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("button", { name: "그리기" }).getAttribute("aria-pressed")).toBe(
      "false"
    );
    expect(screen.queryByRole("button", { name: "선택 지우기" })).toBeNull();
  });

  it("지우기 도구로 누른 것을 바로 지워야 한다", async () => {
    renderConti();
    await openEditor();
    await drawStroke(10);
    await drawStroke(40);
    const [first, second] = sheet().getObjects();

    fireEvent.click(eraseButton());
    await pressOn(first);

    expect(sheet().getObjects()).toEqual([second]);
  });

  it("지운 것이 선택된 채 남지 않아야 한다", async () => {
    // fabric looks the target up once per press and keeps it. An eraser that
    // removes the object before fabric selects it leaves fabric selecting an
    // object that is no longer on the sheet: its handles stay drawn where the
    // stroke was, and a drag moves something nobody can see.
    renderConti();
    await openEditor();
    await drawStroke();

    fireEvent.click(eraseButton());
    await pressOn(sheet().getObjects()[0]);

    expect(sheet().getObjects()).toHaveLength(0);
    expect(sheet().getActiveObject()).toBeUndefined();
  });

  it("지운 것은 실행 취소 한 번에 되살아나야 한다", async () => {
    renderConti();
    await openEditor();
    await drawStroke();

    fireEvent.click(eraseButton());
    await pressOn(sheet().getObjects()[0]);
    expect(sheet().getObjects()).toHaveLength(0);

    await act(async () => {
      fireEvent.click(undoButton());
    });
    expect(sheet().getObjects()).toHaveLength(1);

    // And the step before it is the stroke itself, not a second copy of the
    // erase.
    await act(async () => {
      fireEvent.click(undoButton());
    });
    expect(sheet().getObjects()).toHaveLength(0);
    expect(undoButton().disabled).toBe(true);
  });

  it("빈 곳을 누르면 아무것도 지우지 않아야 한다", async () => {
    renderConti();
    await openEditor();
    await drawStroke();

    fireEvent.click(eraseButton());
    await pressOn(undefined, { x: 100, y: 150 });

    expect(sheet().getObjects()).toHaveLength(1);
    // Nothing filed either: one undo goes straight back past the stroke.
    await act(async () => {
      fireEvent.click(undoButton());
    });
    expect(sheet().getObjects()).toHaveLength(0);
  });

  it("긴 획을 둘러싼 사각형의 빈 곳을 누르면 그 획을 지우지 않아야 한다", async () => {
    // fabric finds targets by bounding box unless told otherwise. A diagonal
    // stroke's box covers a whole corner of the sheet, and a press on the
    // empty paper in it would take the stroke away.
    const { Path } = await import("fabric");
    renderConti();
    await openEditor();
    await act(async () => {
      sheet().add(new Path("M 0 0 L 100 150", { stroke: "#dc2626", fill: "", strokeWidth: 3 }));
    });

    fireEvent.click(eraseButton());
    await pressOn(undefined, { x: 80, y: 20 });

    expect(sheet().getObjects()).toHaveLength(1);
  });

  it("동그라미 안의 짧은 표시를 누르면 그 표시만 지워야 한다", async () => {
    // The circle is drawn later, so it is on top, and its box covers the mark
    // — by box alone the circle would win every press inside it.
    const { Circle, Path } = await import("fabric");
    renderConti();
    await openEditor();
    // Tilted by a unit on purpose: a perfectly flat path has zero height, and
    // fabric's selection area for it contains no point at all (measured) —
    // that would test fabric's box maths rather than the eraser.
    const mark = new Path("M 50 79 L 60 81", { stroke: "#dc2626", fill: "", strokeWidth: 3 });
    const circle = new Circle({
      left: 55,
      top: 80,
      radius: 40,
      fill: "",
      stroke: "#dc2626",
      strokeWidth: 3,
    });
    await act(async () => {
      sheet().add(mark);
      sheet().add(circle);
    });

    fireEvent.click(eraseButton());
    await pressOn(mark);

    expect(sheet().getObjects()).toEqual([circle]);
  });

  it("가는 선은 조금 비껴 눌러도 지워야 한다", async () => {
    // A thin stroke at the fit zoom is a pixel or two wide on screen; pixel
    // hit-testing with no slack would make it nearly impossible to press.
    // (10, 17.5) is 2.5 sheet units below the curve's middle — about three
    // screen pixels past the stroke's edge at this test's zoom.
    renderConti();
    await openEditor();
    await drawStroke(10);

    fireEvent.click(eraseButton());
    await pressOn(undefined, { x: 10, y: 17.5 });

    expect(sheet().getObjects()).toHaveLength(0);
  });

  it("지우기에서 나오면 고르기는 다시 사각형으로 잡아야 한다", async () => {
    // Grabbing by box is what makes a thin stroke easy to pick up and move;
    // the pixel test is for the eraser only.
    renderConti();
    await openEditor();

    fireEvent.click(eraseButton());
    fireEvent.click(screen.getByRole("button", { name: "고르기" }));

    expect(sheet().perPixelTargetFind).toBe(false);
    expect(sheet().targetFindTolerance).toBe(0);
  });

  it("지우기 도구인 채로 닫아도 조용히 닫혀야 한다", async () => {
    // Closing disposes the canvas before the eraser's cleanup runs, and
    // restoring fabric's hit-testing on a disposed canvas throws.
    const errors = [];
    const onError = (event) => {
      errors.push(event.error ?? event.message);
      event.preventDefault();
    };
    window.addEventListener("error", onError);
    try {
      renderConti();
      await openEditor();
      fireEvent.click(eraseButton());
      // Let the render the tool switch requested go out. dispose() waits for a
      // pending render before tearing the canvas down, so closing in the same
      // frame leaves the sampling canvas alive and hides the throw — a leader
      // who picks 지우기 and closes a moment later does not get that luck.
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });

      await act(async () => {
        fireEvent.click(screen.getByRole("button", { name: "닫기" }));
      });

      expect(errors).toEqual([]);
      expect(screen.queryByRole("button", { name: "지우기", exact: true })).toBeNull();
    } finally {
      window.removeEventListener("error", onError);
    }
  });

  it("다른 도구에서는 눌러도 지우지 않아야 한다", async () => {
    renderConti();
    await openEditor();
    await drawStroke();

    fireEvent.click(eraseButton());
    fireEvent.click(screen.getByRole("button", { name: "고르기" }));
    await pressOn(sheet().getObjects()[0]);

    expect(sheet().getObjects()).toHaveLength(1);
  });

  it("지우기 도구에서는 끌어서 여러 개를 고르지 않아야 한다", async () => {
    // A drag on empty sheet would otherwise draw a selection box, which reads
    // as "these are about to be erased" and erases nothing.
    renderConti();
    await openEditor();

    fireEvent.click(eraseButton());
    expect(sheet().selection).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "고르기" }));
    expect(sheet().selection).toBe(true);
  });

  it("글자를 치다 지우기로 바꾸면 쓰던 글자가 닫혀야 한다", async () => {
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "글자" }));
    const label = new IText("", { left: 10, top: 10 });
    await act(async () => {
      sheet().add(label);
      sheet().setActiveObject(label);
      label.enterEditing();
      label.text = "3부";
    });

    await act(async () => {
      fireEvent.click(eraseButton());
    });

    expect(label.isEditing).toBe(false);
    // Switched tools, not deleted: the label being typed is the active object,
    // and 지우기 only deletes a selection made with 고르기.
    expect(sheet().getObjects()).toContain(label);
    expect(eraseButton().getAttribute("aria-pressed")).toBe("true");
  });
});

describe("여러 개 지우기", () => {
  const eraseButton = () => screen.getByRole("button", { name: "지우기", exact: true });
  const selectButton = () => screen.getByRole("button", { name: "고르기" });
  const undoButton = () => screen.getByRole("button", { name: "실행 취소" });

  /** Three strokes, all selected with 고르기 — a rubber band, as fabric makes one. */
  async function selectThreeStrokes() {
    const { ActiveSelection } = await import("fabric");
    await drawStroke(10);
    await drawStroke(40);
    await drawStroke(70);
    fireEvent.click(selectButton());
    await act(async () => {
      const canvas = sheet();
      canvas.setActiveObject(new ActiveSelection(canvas.getObjects(), { canvas }));
    });
  }

  const keyDown = (key) => {
    const event = new KeyboardEvent("keydown", { key, cancelable: true, bubbles: true });
    act(() => {
      window.dispatchEvent(event);
    });
    return event;
  };

  it("고르기로 여러 개를 고르고 지우기를 누르면 한꺼번에 지워야 한다", async () => {
    renderConti();
    await openEditor();
    await selectThreeStrokes();

    await act(async () => {
      fireEvent.click(eraseButton());
    });

    expect(sheet().getObjects()).toHaveLength(0);
    // No selection left behind: its handles would stay drawn over empty sheet.
    expect(sheet().getActiveObject()).toBeUndefined();
    // Stays on 고르기: the press deleted, it did not change tools.
    expect(selectButton().getAttribute("aria-pressed")).toBe("true");
    expect(eraseButton().getAttribute("aria-pressed")).toBe("false");
  });

  it("한꺼번에 지운 것은 실행 취소 한 번에 돌아와야 한다", async () => {
    // Removed one by one, one event each; filed one by one, a single press of
    // 지우기 would take three presses of 실행 취소 to come back.
    renderConti();
    await openEditor();
    await selectThreeStrokes();

    await act(async () => {
      fireEvent.click(eraseButton());
    });
    await act(async () => {
      fireEvent.click(undoButton());
    });

    expect(sheet().getObjects()).toHaveLength(3);
  });

  it("고르기에서 고른 것이 없으면 지우기는 도구로 바뀌어야 한다", async () => {
    renderConti();
    await openEditor();
    await drawStroke();
    fireEvent.click(selectButton());

    await act(async () => {
      fireEvent.click(eraseButton());
    });

    expect(sheet().getObjects()).toHaveLength(1);
    expect(eraseButton().getAttribute("aria-pressed")).toBe("true");
  });

  it("고른 것을 Delete 키로 지워야 한다", async () => {
    renderConti();
    await openEditor();
    await selectThreeStrokes();

    const event = keyDown("Delete");

    expect(sheet().getObjects()).toHaveLength(0);
    expect(event.defaultPrevented).toBe(true);
  });

  it("고른 것을 Backspace 키로도 지워야 한다", async () => {
    renderConti();
    await openEditor();
    await selectThreeStrokes();

    keyDown("Backspace");

    expect(sheet().getObjects()).toHaveLength(0);
  });

  it("글자를 고쳐 쓰는 중에는 Delete 키가 글자를 지우지 않아야 한다", async () => {
    // The key belongs to the label then: it deletes a letter, not the label.
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();
    fireEvent.click(selectButton());
    const label = new IText("3부", { left: 10, top: 10 });
    await act(async () => {
      sheet().add(label);
      sheet().setActiveObject(label);
      label.enterEditing();
    });

    const event = keyDown("Backspace");

    expect(sheet().getObjects()).toContain(label);
    expect(event.defaultPrevented).toBe(false);
  });

  it("고른 것이 없으면 Delete 키를 가로채지 않아야 한다", async () => {
    renderConti();
    await openEditor();
    await drawStroke();
    fireEvent.click(selectButton());

    const event = keyDown("Delete");

    expect(sheet().getObjects()).toHaveLength(1);
    expect(event.defaultPrevented).toBe(false);
  });

  it("고르기가 아닌 도구에서는 Delete 키로 지우지 않아야 한다", async () => {
    renderConti();
    await openEditor();
    await selectThreeStrokes();
    // Selecting again behind the tool's back: the draw tool discards the
    // selection when chosen, so this is the only way to have both at once.
    const { ActiveSelection } = await import("fabric");
    fireEvent.click(screen.getByRole("button", { name: "그리기" }));
    await act(async () => {
      const canvas = sheet();
      canvas.setActiveObject(new ActiveSelection(canvas.getObjects(), { canvas }));
    });

    keyDown("Delete");

    expect(sheet().getObjects()).toHaveLength(3);
  });

  it("저장하는 중에는 Delete 키로 지우지 않아야 한다", async () => {
    // Same reason as Ctrl+Z: the request carries a sheet exported before the
    // key, and deleting now would store one picture and show another.
    const { ActiveSelection } = await import("fabric");
    mockApi({ save: { pending: true } });
    renderConti();
    await openEditor();
    await drawStroke();
    fireEvent.click(selectButton());

    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "저장하는 중…" })).toBeTruthy());
    // The export discarded the selection; select again so the key has
    // something it could delete.
    await act(async () => {
      const canvas = sheet();
      canvas.setActiveObject(new ActiveSelection(canvas.getObjects(), { canvas }));
    });
    keyDown("Delete");

    expect(sheet().getObjects()).toHaveLength(1);
  });
});

describe("선 굵기", () => {
  const widthButton = (name) => screen.getByRole("button", { name });

  it("처음에는 보통 굵기로 그려야 한다", async () => {
    // The width every sheet was drawn with before there was a choice, so a
    // leader who never touches the control marks up the same as before.
    renderConti();
    await openEditor();

    expect(widthButton("선 보통").getAttribute("aria-pressed")).toBe("true");
    // Waited for: openEditor returns on the render that enables the buttons,
    // and the width is applied by an effect that runs after that render — so
    // reading it at once failed about one run in seven.
    await waitFor(() => expect(sheet().freeDrawingBrush.width).toBe(3));
  });

  it("굵게를 고르면 그 굵기로 그려야 한다", async () => {
    renderConti();
    await openEditor();
    const canvasCount = canvases.length;

    await act(async () => {
      fireEvent.click(widthButton("선 굵게"));
    });

    expect(widthButton("선 굵게").getAttribute("aria-pressed")).toBe("true");
    expect(widthButton("선 보통").getAttribute("aria-pressed")).toBe("false");
    expect(sheet().freeDrawingBrush.width).toBe(6);
    // Same canvas, not a rebuilt one — a rebuild would drop the drawing.
    expect(canvases).toHaveLength(canvasCount);
  });

  it("얇게를 고르면 그 굵기로 그려야 한다", async () => {
    renderConti();
    await openEditor();

    await act(async () => {
      fireEvent.click(widthButton("선 얇게"));
    });

    expect(sheet().freeDrawingBrush.width).toBe(1.5);
  });

  it("이미 그린 선의 굵기는 바꾸지 않아야 한다", async () => {
    // Same rule as colour: the control sets the next stroke, not the ones
    // already on the sheet.
    renderConti();
    await openEditor();
    await drawStroke();

    await act(async () => {
      fireEvent.click(widthButton("선 굵게"));
    });

    const [stroke] = sheet()
      .getObjects()
      .filter((o) => o.type === "path");
    expect(stroke.strokeWidth).toBe(3);
  });

  it("글자를 치는 중에 굵기를 바꿔도 편집이 닫히지 않아야 한다", async () => {
    // Changing the tool closes a label on purpose; changing the width is not
    // changing the tool, and closing there would commit a half-typed word.
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();

    fireEvent.click(screen.getByRole("button", { name: "글자" }));
    const label = new IText("", { left: 10, top: 10 });
    await act(async () => {
      sheet().add(label);
      sheet().setActiveObject(label);
      label.enterEditing();
      label.text = "3부";
    });

    await act(async () => {
      fireEvent.click(widthButton("선 굵게"));
    });

    expect(label.isEditing).toBe(true);
  });
});

describe("글자 크기", () => {
  const sizeButton = (name) => screen.getByRole("button", { name });

  /** Places a label the way a click with the text tool does.
   *
   * The click itself never reaches fabric here, so the event it would have
   * produced is fired at the canvas instead — which runs the app's own
   * handler, and with it whatever size that handler reads.
   */
  async function placeLabel() {
    await act(async () => {
      sheet().fire("mouse:down", {
        e: new MouseEvent("mousedown", { clientX: 5, clientY: 5 }),
        target: undefined,
      });
    });
    let label;
    await waitFor(() => {
      label = sheet()
        .getObjects()
        .find((o) => o.type === "i-text");
      expect(label).toBeTruthy();
    });
    return label;
  }

  /** A label with "3부" typed into it and still open. */
  async function typingLabel() {
    const { IText } = await import("fabric");
    const label = new IText("", { left: 10, top: 10 });
    await act(async () => {
      sheet().add(label);
      sheet().setActiveObject(label);
      label.enterEditing();
      label.text = "3부";
    });
    return label;
  }

  it("처음에는 보통 크기로 글자를 놓아야 한다", async () => {
    renderConti();
    await openEditor();
    fireEvent.click(screen.getByRole("button", { name: "글자" }));

    expect(sizeButton("글자 보통").getAttribute("aria-pressed")).toBe("true");
    expect((await placeLabel()).fontSize).toBe(24);
  });

  it("크게를 고르면 새 글자를 그 크기로 놓아야 한다", async () => {
    renderConti();
    await openEditor();
    fireEvent.click(screen.getByRole("button", { name: "글자" }));

    await act(async () => {
      fireEvent.click(sizeButton("글자 크게"));
    });

    expect(sizeButton("글자 크게").getAttribute("aria-pressed")).toBe("true");
    expect(sizeButton("글자 보통").getAttribute("aria-pressed")).toBe("false");
    expect((await placeLabel()).fontSize).toBe(36);
  });

  it("작게를 고르면 새 글자를 그 크기로 놓아야 한다", async () => {
    renderConti();
    await openEditor();
    fireEvent.click(screen.getByRole("button", { name: "글자" }));

    await act(async () => {
      fireEvent.click(sizeButton("글자 작게"));
    });

    expect((await placeLabel()).fontSize).toBe(16);
  });

  it("이미 쓴 글자의 크기는 바꾸지 않아야 한다", async () => {
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();
    const label = new IText("3부", { left: 10, top: 10, fontSize: 24 });
    await act(async () => {
      sheet().add(label);
    });

    await act(async () => {
      fireEvent.click(sizeButton("글자 크게"));
    });

    expect(label.fontSize).toBe(24);
  });

  it("글자를 치는 중에 크기를 바꿔도 편집이 닫히지 않아야 한다", async () => {
    renderConti();
    await openEditor();
    fireEvent.click(screen.getByRole("button", { name: "글자" }));
    const label = await typingLabel();

    await act(async () => {
      fireEvent.click(sizeButton("글자 크게"));
    });

    expect(label.isEditing).toBe(true);
  });

  it("글자를 치는 중에 크기를 바꾸면 치던 글자로 돌아가야 한다", async () => {
    // A real click moves focus to the button, and fabric reads keys only from
    // its hidden textarea — so without this the next letters go nowhere.
    // jsdom does not move focus on click, so the press does it by hand.
    renderConti();
    await openEditor();
    fireEvent.click(screen.getByRole("button", { name: "글자" }));
    const label = await typingLabel();

    const button = sizeButton("글자 크게");
    button.focus();
    expect(document.activeElement).toBe(button);
    await act(async () => {
      fireEvent.click(button);
    });

    expect(document.activeElement).toBe(label.hiddenTextarea);
  });

  it("치는 글자가 없어도 크기를 바꿀 수 있어야 한다", async () => {
    // Nothing is selected, so there is no label to hand focus back to. A throw
    // in the click handler would not fail the press on its own — React reports
    // it and moves on — so the error is listened for directly.
    const errors = [];
    const onError = (event) => {
      errors.push(event.error ?? event.message);
      event.preventDefault();
    };
    window.addEventListener("error", onError);
    try {
      renderConti();
      await openEditor();

      const button = sizeButton("글자 크게");
      button.focus();
      await act(async () => {
        fireEvent.click(button);
      });

      expect(errors).toEqual([]);
      expect(button.getAttribute("aria-pressed")).toBe("true");
      expect(document.activeElement).toBe(button);
    } finally {
      window.removeEventListener("error", onError);
    }
  });
});

describe("실행 취소", () => {
  const undoButton = () => screen.getByRole("button", { name: "실행 취소" });

  it("연 직후에는 실행 취소를 누를 수 없어야 한다", async () => {
    renderConti();
    await openEditor();

    // Nothing of the leader's own has happened yet, so there is nothing to
    // take back — and the sheet as it opened is the floor, not a step.
    expect(undoButton().disabled).toBe(true);
  });

  it("저장된 편집을 열어도 실행 취소를 누를 수 없어야 한다", async () => {
    // The seed is replayed with loadFromJSON, which fires object:added for
    // every object it restores. Subscribing before that replay would file the
    // whole saved edit as steps the leader could undo their way out of.
    mockApi({
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

    expect(sheet().getObjects()).toHaveLength(1);
    expect(undoButton().disabled).toBe(true);
  });

  it("그리고 나면 실행 취소를 누를 수 있어야 한다", async () => {
    renderConti();
    await openEditor();

    await drawStroke();

    expect(undoButton().disabled).toBe(false);
  });

  it("실행 취소를 누르면 방금 그린 것이 사라져야 한다", async () => {
    renderConti();
    await openEditor();
    await drawStroke();
    expect(sheet().getObjects()).toHaveLength(1);

    await act(async () => {
      fireEvent.click(undoButton());
    });

    expect(sheet().getObjects()).toHaveLength(0);
  });

  it("실행 취소를 해도 악보는 그대로 깔려 있어야 한다", async () => {
    // loadFromJSON replaces the whole canvas, background included, and the
    // stored document deliberately carries none. Without re-attaching it the
    // first undo would leave the leader drawing on nothing.
    renderConti();
    await openEditor();
    await drawStroke();

    await act(async () => {
      fireEvent.click(undoButton());
    });

    expect(sheet().backgroundImage).toBeTruthy();
  });

  it("연속으로 되돌리면 한 획씩 거슬러야 한다", async () => {
    renderConti();
    await openEditor();
    await drawStroke(10);
    await drawStroke(40);
    await drawStroke(70);

    await act(async () => {
      fireEvent.click(undoButton());
    });
    expect(sheet().getObjects()).toHaveLength(2);

    await act(async () => {
      fireEvent.click(undoButton());
    });
    expect(sheet().getObjects()).toHaveLength(1);
  });

  it("연 상태까지 되돌리면 더는 누를 수 없어야 한다", async () => {
    // Also the guard against undo recording itself: restoring fires
    // object:removed and object:added, and filing those would keep the button
    // alive forever while the sheet stopped changing.
    renderConti();
    await openEditor();
    await drawStroke();

    await act(async () => {
      fireEvent.click(undoButton());
    });

    expect(sheet().getObjects()).toHaveLength(0);
    expect(undoButton().disabled).toBe(true);
  });

  it("되돌린 상태가 저장돼야 한다", async () => {
    // The sheet on screen and the sheet in the row have to be the same one.
    const calls = mockApi();
    renderConti();
    await openEditor();
    await drawStroke(10);
    await drawStroke(40);

    await act(async () => {
      fireEvent.click(undoButton());
    });
    fireEvent.click(screen.getByRole("button", { name: "저장" }));

    await waitFor(() => expect(callsTo(calls, "/scores/a/edit", "PUT")).toHaveLength(1));
    const saved = callsTo(calls, "/scores/a/edit", "PUT")[0].body;
    expect(saved.edit_doc.objects).toHaveLength(1);
  });

  it("Ctrl+Z 로도 되돌려야 한다", async () => {
    // The button is the tablet's way in; this is the desk's.
    renderConti();
    await openEditor();
    await drawStroke();

    const event = new KeyboardEvent("keydown", {
      key: "z",
      ctrlKey: true,
      cancelable: true,
      bubbles: true,
    });
    await act(async () => {
      window.dispatchEvent(event);
    });

    expect(sheet().getObjects()).toHaveLength(0);
    // Claimed, so the browser's own undo does not also run on whatever else
    // the page has focus in.
    expect(event.defaultPrevented).toBe(true);
  });

  it("Cmd+Z 로도 되돌려야 한다", async () => {
    renderConti();
    await openEditor();
    await drawStroke();

    await act(async () => {
      fireEvent.keyDown(window, { key: "z", metaKey: true });
    });

    expect(sheet().getObjects()).toHaveLength(0);
  });

  it("Shift 를 같이 누르면 되돌리지 않아야 한다", async () => {
    // Ctrl+Shift+Z is redo everywhere else. Doing the opposite of what was
    // asked is worse than doing nothing.
    renderConti();
    await openEditor();
    await drawStroke();

    await act(async () => {
      fireEvent.keyDown(window, { key: "Z", ctrlKey: true, shiftKey: true });
    });

    expect(sheet().getObjects()).toHaveLength(1);
  });

  it("편집기를 닫으면 Ctrl+Z 를 가로채지 않아야 한다", async () => {
    // The listener is on the window, so one left behind would swallow undo on
    // every other screen of the app.
    renderConti();
    await openEditor();
    await drawStroke();
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));

    const event = new KeyboardEvent("keydown", {
      key: "z",
      ctrlKey: true,
      cancelable: true,
      bubbles: true,
    });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });

  it("빈 글자를 만들었다 그만두면 실행 취소가 열리지 않아야 한다", async () => {
    // The text tool adds an empty IText on click and drops it again when the
    // leader walks away. Filing both would leave two presses to get back to
    // where they already are, and neither of them would change the picture.
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();

    await act(async () => {
      const blank = new IText("", { left: 10, top: 10 });
      sheet().add(blank);
      sheet().remove(blank);
    });

    expect(undoButton().disabled).toBe(true);
  });

  it("글자를 쓰고 나면 실행 취소를 누를 수 있어야 한다", async () => {
    // The other half of the rule above: a label that was actually typed is a
    // step, and it is the modified event at the end of editing that files it.
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();

    await act(async () => {
      const label = new IText("3부", { left: 10, top: 10 });
      sheet().add(label);
    });

    expect(undoButton().disabled).toBe(false);
  });
});

describe("실행 취소 — 듣지 말아야 할 때", () => {
  it("되돌릴 것이 없으면 Ctrl+Z 를 가로채지 않아야 한다", async () => {
    // The key belongs to the browser until this editor has something of its
    // own to take back.
    renderConti();
    await openEditor();

    const event = new KeyboardEvent("keydown", {
      key: "z",
      ctrlKey: true,
      cancelable: true,
      bubbles: true,
    });
    window.dispatchEvent(event);

    expect(event.defaultPrevented).toBe(false);
  });

  it("저장하는 중에는 Ctrl+Z 로 되돌릴 수 없어야 한다", async () => {
    // The request already carries a png exported before the key was pressed.
    // Undoing now would store one picture and leave another on screen.
    mockApi({ save: { pending: true } });
    renderConti();
    await openEditor();
    await drawStroke();

    fireEvent.click(screen.getByRole("button", { name: "저장" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "저장하는 중…" })).toBeTruthy());
    await act(async () => {
      fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    });

    expect(sheet().getObjects()).toHaveLength(1);
  });
});

describe("실행 취소 — 글자를 치는 중", () => {
  it("빈 글자를 열어둔 채 누르면 그 앞 단계가 되돌아가야 한다", async () => {
    // Placing a label and pressing 실행 취소 before typing anything: the empty
    // IText was never a step — it draws nothing, so filing it would have cost
    // a press that changed nothing on screen — and the press falls through to
    // the stroke before it, which is the last thing the leader can actually
    // see.
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();
    await drawStroke();

    await act(async () => {
      const label = new IText("", { left: 10, top: 10 });
      sheet().add(label);
      sheet().setActiveObject(label);
      label.enterEditing();
    });
    await act(async () => {
      fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    });

    expect(
      sheet()
        .getObjects()
        .filter((object) => object.type === "path")
    ).toHaveLength(0);
  });
});

describe("실행 취소 — 코드리뷰가 짚은 것", () => {
  const undoButton = () => screen.getByRole("button", { name: "실행 취소" });

  it("글자를 치는 중에 눌러도 되돌아가야 한다", async () => {
    // fabric does not end editing when focus leaves the canvas — the hidden
    // textarea's blur leaves isEditing true (measured) — so a toolbar press
    // used to hit a guard and do nothing at all while the button sat enabled.
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();
    await drawStroke();

    // The text tool's real order: an empty label is placed (not a step, it
    // draws nothing) and the letters arrive afterwards. Only closing the
    // editing session turns that into something history can see — fabric
    // fires object:modified from exitEditing, and only when the text changed.
    await act(async () => {
      const label = new IText("", { left: 10, top: 10 });
      sheet().add(label);
      sheet().setActiveObject(label);
      label.enterEditing();
      label.text = "3부";
    });
    await act(async () => {
      fireEvent.click(undoButton());
    });

    // The label was closed, filed as a step, and that step taken back: the
    // stroke stays, the word just typed is gone. Without the close the press
    // would fall through to the stroke and take that instead.
    expect(
      sheet()
        .getObjects()
        .filter((o) => o.type === "i-text")
    ).toHaveLength(0);
    expect(
      sheet()
        .getObjects()
        .filter((o) => o.type === "path")
    ).toHaveLength(1);
  });

  it("Ctrl+Z 도 글자를 치는 중에 되돌려야 한다", async () => {
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();
    await drawStroke();

    await act(async () => {
      const label = new IText("", { left: 10, top: 10 });
      sheet().add(label);
      sheet().setActiveObject(label);
      label.enterEditing();
      label.text = "3부";
    });
    await act(async () => {
      fireEvent.keyDown(window, { key: "z", ctrlKey: true });
    });

    expect(
      sheet()
        .getObjects()
        .filter((o) => o.type === "i-text")
    ).toHaveLength(0);
    expect(
      sheet()
        .getObjects()
        .filter((o) => o.type === "path")
    ).toHaveLength(1);
  });

  it("쓰여 있던 글자를 지우면 그 지움도 되돌릴 수 있어야 한다", async () => {
    // fabric fires object:modified after text:editing:exited with the label
    // already empty. Filtering blanks out of modified as well would lose this
    // change entirely: the history would still claim "3부" is on the sheet.
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();

    const label = new IText("3부", { left: 10, top: 10 });
    await act(async () => {
      sheet().add(label);
      sheet().setActiveObject(label);
    });
    await act(async () => {
      label.enterEditing();
      label.text = "";
      label.exitEditing();
    });

    await act(async () => {
      fireEvent.click(undoButton());
    });

    const labels = sheet()
      .getObjects()
      .filter((o) => o.type === "i-text");
    expect(labels).toHaveLength(1);
    expect(labels[0].text).toBe("3부");
  });

  it("되돌리는 중에 또 누르면 두 단계가 한꺼번에 사라지지 않아야 한다", async () => {
    // The restore is awaited, and a second press landing inside that await
    // takes another step off the stack while the first is still replaying —
    // two strokes gone for one press the leader can account for, and the
    // second finally clearing the suspend flag the first still needs.
    renderConti();
    await openEditor();
    await drawStroke(10);
    await drawStroke(40);
    await drawStroke(70);

    let release;
    holdLoad = new Promise((resolve) => {
      release = resolve;
    });

    await act(async () => {
      fireEvent.click(undoButton());
      fireEvent.click(undoButton());
    });
    holdLoad = null;
    await act(async () => {
      release();
    });

    // Counted by what the stack has left rather than by what is on screen:
    // when two restores overlap, which of them lands last is not fixed, but
    // how many steps were taken off is. A dropped second press leaves the
    // next undo on the second stroke; a second press that got through would
    // already have spent it, and this would come back empty.
    await act(async () => {
      fireEvent.click(undoButton());
    });

    expect(sheet().getObjects()).toHaveLength(1);
  });
});

describe("실행 취소 — 되돌리는 중에 닫으면", () => {
  it("편집기를 닫아도 조용히 끝나야 한다", async () => {
    // The restore is awaited and the cleanup disposes the canvas, so a close
    // that lands inside that await leaves undo holding a canvas that is gone.
    //
    // ★ This does NOT verify the `fabricRef.current !== canvas` guard that
    // undo carries: fabric 7 accepts the calls on a disposed canvas without
    // complaint, so the test passes with the guard removed (measured). It
    // pins the behaviour — closing mid-undo stays quiet — and would catch a
    // future fabric that starts throwing. The guard itself is unverified, and
    // kept because the path is real and it costs one line.
    renderConti();
    await openEditor();
    await drawStroke();

    let release;
    holdLoad = new Promise((resolve) => {
      release = resolve;
    });
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "실행 취소" }));
    });
    fireEvent.click(screen.getByRole("button", { name: "닫기" }));
    holdLoad = null;
    const rejections = [];
    const onRejection = (event) => {
      rejections.push(event.reason);
      event.preventDefault();
    };
    window.addEventListener("unhandledrejection", onRejection);
    await act(async () => {
      release();
    });
    await act(async () => {
      await Promise.resolve();
    });
    window.removeEventListener("unhandledrejection", onRejection);

    expect(rejections).toHaveLength(0);
    expect(screen.queryByRole("button", { name: "저장" })).toBeNull();
  });
});

describe("실행 취소 — 도구를 바꿔 글자를 끝냈을 때", () => {
  it("도구를 바꾸면 쓰던 글자가 한 단계로 남아야 한다", async () => {
    // fabric does not end editing when focus moves to a toolbar button, so a
    // label finished that way never fires object:modified. Unrecorded, the
    // next 실행 취소 takes back the stroke before it and the label stays —
    // the opposite of what the press asked for.
    const { IText } = await import("fabric");
    renderConti();
    await openEditor();
    await drawStroke();

    fireEvent.click(screen.getByRole("button", { name: "글자" }));
    const label = new IText("", { left: 10, top: 10 });
    await act(async () => {
      sheet().add(label);
      sheet().setActiveObject(label);
      label.enterEditing();
      label.text = "3부";
    });

    // Leaving the text tool is what has to close it.
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "고르기" }));
    });
    expect(label.isEditing).toBe(false);

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "실행 취소" }));
    });

    // The label goes, the stroke stays.
    expect(
      sheet()
        .getObjects()
        .filter((o) => o.type === "i-text")
    ).toHaveLength(0);
    expect(
      sheet()
        .getObjects()
        .filter((o) => o.type === "path")
    ).toHaveLength(1);
  });
});
