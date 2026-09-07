/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { saveBlobAsFile } from "./download";

const OBJECT_URL = "blob:http://localhost:5173/9f2c-4d10";

// jsdom implements neither of these, so without stubs saveBlobAsFile throws
// before it ever reaches the anchor. Built fresh per test rather than shared:
// vi.restoreAllMocks() strips a vi.fn()'s implementation, which would leave the
// second test's createObjectURL answering undefined.
function makeUrlStubs() {
  return { createObjectURL: vi.fn(() => OBJECT_URL), revokeObjectURL: vi.fn() };
}

let urlStubs: ReturnType<typeof makeUrlStubs>;

// The anchor is never attached to the document, so the click spy's receiver is
// the only handle on it. Recording href/download *at click time* is what makes
// this a test rather than a restatement: a version that clicked before setting
// `download` would still leave the right attributes behind afterwards.
let clicks: { href: string; download: string }[] = [];

beforeEach(() => {
  // Fake for every test, not just the one that advances them: saveBlobAsFile
  // revokes from a setTimeout, and a real one left pending by an earlier test
  // fires during the next one and records against its fresh stub.
  vi.useFakeTimers();
  urlStubs = makeUrlStubs();
  // Configurable so afterEach can take them back off; the next file then starts
  // from jsdom's real, empty URL rather than inheriting this one's stubs.
  Object.defineProperty(URL, "createObjectURL", {
    value: urlStubs.createObjectURL,
    configurable: true,
  });
  Object.defineProperty(URL, "revokeObjectURL", {
    value: urlStubs.revokeObjectURL,
    configurable: true,
  });

  clicks = [];
  // Real navigation is what must not happen here: jsdom answers a download
  // click with "Not implemented: navigation", and that warning is this repo's
  // signal that a test is tearing down its own session. Firing it harmlessly
  // would train the next reader to scroll past the real one.
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement
  ) {
    clicks.push({ href: this.href, download: this.download });
  });
});

afterEach(() => {
  vi.useRealTimers();
  vi.restoreAllMocks();
  Reflect.deleteProperty(URL, "createObjectURL");
  Reflect.deleteProperty(URL, "revokeObjectURL");
});

describe("saveBlobAsFile", () => {
  it("받은 blob의 주소를 주어진 파일 이름으로 클릭해야 한다", () => {
    // Arrange
    const blob = new Blob(["%PDF-1.4"], { type: "application/pdf" });

    // Act
    saveBlobAsFile(blob, "conti-2026-09-13.pdf");

    // Assert
    expect(urlStubs.createObjectURL.mock.calls).toEqual([[blob]]);
    expect(clicks).toEqual([{ href: OBJECT_URL, download: "conti-2026-09-13.pdf" }]);
  });

  it("클릭한 뒤 다음 태스크에서 object URL을 되돌려야 한다", async () => {
    // Arrange — revoking first hands the browser a dead URL: the download
    // quietly produces nothing, and dropping the revoke instead leaks the blob
    // for the lifetime of the document. Revoking in the *same* task is the
    // third failure: Firefox and Safari can abort a transfer already under way.
    const clickSpy = vi.mocked(HTMLAnchorElement.prototype.click);

    // Act
    saveBlobAsFile(new Blob(["%PDF-1.4"]), "conti-2026-09-13.pdf");

    // Assert — not yet, and only after the turn of the event loop
    expect(urlStubs.revokeObjectURL).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(0);
    expect(urlStubs.revokeObjectURL.mock.calls).toEqual([[OBJECT_URL]]);
    expect(urlStubs.revokeObjectURL.mock.invocationCallOrder[0]).toBeGreaterThan(
      clickSpy.mock.invocationCallOrder[0]
    );
  });

  it("클릭할 때 앵커가 문서에 붙어 있어야 한다", () => {
    // Arrange — Firefox does not start a download from a detached anchor.
    let attachedAtClick = false;
    vi.mocked(HTMLAnchorElement.prototype.click).mockImplementation(function (
      this: HTMLAnchorElement
    ) {
      attachedAtClick = this.isConnected;
    });

    // Act
    saveBlobAsFile(new Blob(["%PDF-1.4"]), "conti-2026-09-13.pdf");

    // Assert
    expect(attachedAtClick).toBe(true);
  });
});
