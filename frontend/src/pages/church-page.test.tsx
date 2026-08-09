/**
 * @vitest-environment jsdom
 *
 * Page-level tests for the leader's invite code screen. What matters here is
 * that rotation is deliberate and that its result reaches the screen: the old
 * code stops working the instant the server answers, so a success the page
 * failed to show would leave a leader handing out a dead string.
 *
 * fireEvent rather than user-event, for the same reason as signup-page.test.tsx.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import ChurchPage from "./church-page";

const LEADER_SESSION = {
  user: { role: "leader" },
  church: { name: "한빛교회", code: "abcd2345" },
};

const MEMBER_SESSION = {
  user: { role: "member" },
  church: { name: "한빛교회", code: null },
};

type Reply = { status?: number; body?: unknown };

function mockApi({ session, rotate }: { session: unknown; rotate?: Reply }) {
  vi.stubGlobal(
    "fetch",
    vi.fn((_input: RequestInfo | URL, init?: RequestInit) => {
      // Only two calls reach this page and only one of them is a POST, so the
      // method is enough to tell them apart.
      const isRotate = init?.method === "POST";
      const reply: Reply = isRotate ? (rotate ?? { body: {} }) : { body: session };
      const status = reply.status ?? 200;
      return Promise.resolve({
        ok: status < 400,
        status,
        json: async () => reply.body,
      } as Response);
    })
  );
}

const renderChurchPage = () =>
  render(
    // The page renders a <Link>, which needs a router above it.
    <MemoryRouter>
      <ChurchPage />
    </MemoryRouter>
  );

const rotateButton = () => screen.getByRole("button", { name: "초대 코드 재발급" });
const copyButton = (name: string) => screen.getByRole("button", { name });

/**
 * jsdom implements no Clipboard API, so the copy button has nothing to call
 * without this. Defined as configurable so afterEach can take it back off and
 * the next test starts from jsdom's real, empty navigator.
 */
function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  Reflect.deleteProperty(navigator, "clipboard");
});

describe("교회 초대 코드 화면", () => {
  it("리더면 지금 쓰이는 코드를 보여줘야 한다", async () => {
    mockApi({ session: LEADER_SESSION });
    renderChurchPage();

    // Read from /auth/me rather than kept from signup, so a leader who returns
    // later — or who has rotated since — sees the one that actually works.
    expect(await screen.findByText("abcd2345")).toBeTruthy();
    expect(screen.getByText("한빛교회")).toBeTruthy();
  });

  it("멤버면 코드 대신 리더만 볼 수 있다고 안내해야 한다", async () => {
    mockApi({ session: MEMBER_SESSION });
    renderChurchPage();

    expect(await screen.findByText("초대 코드는 교회 리더만 확인할 수 있습니다.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "초대 코드 재발급" })).toBeNull();
  });

  it("재발급 확인을 취소하면 요청을 보내지 않아야 한다", async () => {
    mockApi({ session: LEADER_SESSION, rotate: { body: { code: "wxyz6789" } } });
    renderChurchPage();
    await screen.findByText("abcd2345");
    vi.spyOn(window, "confirm").mockReturnValue(false);

    fireEvent.click(rotateButton());

    // Irreversible and immediate: everyone holding the old code loses access the
    // moment it succeeds, so a mis-click must not be enough.
    await waitFor(() => expect(screen.getByText("abcd2345")).toBeTruthy());
    expect(vi.mocked(fetch)).toHaveBeenCalledTimes(1);
  });

  it("재발급에 성공하면 새 코드로 바꿔 보여줘야 한다", async () => {
    mockApi({ session: LEADER_SESSION, rotate: { body: { code: "wxyz6789" } } });
    renderChurchPage();
    await screen.findByText("abcd2345");
    vi.spyOn(window, "confirm").mockReturnValue(true);

    fireEvent.click(rotateButton());

    expect(await screen.findByText("wxyz6789")).toBeTruthy();
    expect(screen.queryByText("abcd2345")).toBeNull();
  });

  it("코드를 복사하면 복사됐다고 알려야 한다", async () => {
    const writeText = stubClipboard();
    mockApi({ session: LEADER_SESSION });
    renderChurchPage();
    await screen.findByText("abcd2345");

    fireEvent.click(copyButton("복사"));

    expect(await screen.findByRole("button", { name: "복사됨" })).toBeTruthy();
    expect(writeText).toHaveBeenCalledWith("abcd2345");
  });

  it("복사가 막히면 실패했다고 알리고 코드는 그대로 둬야 한다", async () => {
    // The Clipboard API needs a secure context and a permission, so this is a
    // real outcome, not a defensive branch. Saying "복사됨" when nothing was
    // copied is worse than saying nothing: the code stays selectable either way,
    // but only one of the two answers tells the leader to select it by hand.
    const writeText = stubClipboard();
    writeText.mockRejectedValue(new Error("blocked"));
    mockApi({ session: LEADER_SESSION });
    renderChurchPage();
    await screen.findByText("abcd2345");

    fireEvent.click(copyButton("복사"));

    expect(await screen.findByRole("button", { name: "복사 실패" })).toBeTruthy();
    expect(screen.getByText("abcd2345")).toBeTruthy();
  });

  it("재발급하면 복사됨 표시가 사라져야 한다", async () => {
    // Rotation kills the old code the instant the server answers, but the
    // clipboard still holds it. A "복사됨" left standing next to the new code
    // says the new one is ready to paste; pasting it hands out a dead string
    // and the person on the other end gets a 403 they cannot explain.
    stubClipboard();
    mockApi({ session: LEADER_SESSION, rotate: { body: { code: "wxyz6789" } } });
    renderChurchPage();
    await screen.findByText("abcd2345");
    fireEvent.click(copyButton("복사"));
    await screen.findByRole("button", { name: "복사됨" });
    vi.spyOn(window, "confirm").mockReturnValue(true);

    fireEvent.click(rotateButton());

    await screen.findByText("wxyz6789");
    expect(copyButton("복사")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "복사됨" })).toBeNull();
  });

  it("재발급하지 않는 한 복사됨 표시는 유지돼야 한다", async () => {
    // Without this the test above is satisfied by never showing "복사됨" at all,
    // which is not a fix — it is the feature removed.
    stubClipboard();
    mockApi({ session: LEADER_SESSION, rotate: { body: { code: "wxyz6789" } } });
    renderChurchPage();
    await screen.findByText("abcd2345");
    fireEvent.click(copyButton("복사"));
    await screen.findByRole("button", { name: "복사됨" });
    vi.spyOn(window, "confirm").mockReturnValue(false);

    fireEvent.click(rotateButton());

    await waitFor(() => expect(screen.getByText("abcd2345")).toBeTruthy());
    expect(copyButton("복사됨")).toBeTruthy();
  });

  it("재발급이 거부되면 이유를 보여주고 옛 코드를 그대로 둬야 한다", async () => {
    mockApi({
      session: LEADER_SESSION,
      rotate: { status: 403, body: { detail: "교회 리더만 초대 코드를 관리할 수 있습니다." } },
    });
    renderChurchPage();
    await screen.findByText("abcd2345");
    vi.spyOn(window, "confirm").mockReturnValue(true);

    fireEvent.click(rotateButton());

    expect(await screen.findByText("교회 리더만 초대 코드를 관리할 수 있습니다.")).toBeTruthy();
    // Nothing changed server-side, so showing anything else would be a lie.
    expect(screen.getByText("abcd2345")).toBeTruthy();
  });

  it("재발급은 됐는데 코드를 못 읽으면 새로고침을 안내해야 한다", async () => {
    // The old code has already stopped working, so this must not read as
    // "nothing happened".
    mockApi({ session: LEADER_SESSION, rotate: { body: { code: 12345 } } });
    renderChurchPage();
    await screen.findByText("abcd2345");
    vi.spyOn(window, "confirm").mockReturnValue(true);

    fireEvent.click(rotateButton());

    expect(
      await screen.findByText("코드는 재발급됐지만 화면에 표시하지 못했습니다. 새로고침해 주세요.")
    ).toBeTruthy();
  });
});
