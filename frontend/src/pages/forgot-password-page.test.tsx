/**
 * @vitest-environment jsdom
 *
 * Page-level tests for the reset request form.
 *
 * The rule worth defending here is not a validation rule: it is that this screen
 * never reveals whether an address is registered. The server guarantees that by
 * answering 202 for everyone, and the only way to lose it on this side is copy —
 * so the confirmation text is asserted as behaviour, not left to review.
 *
 * Input goes through fireEvent rather than user-event, matching signup-page's
 * tests: user-event deadlocks against a fake clock unless the clock is allowed
 * to track real time, which would make assertions depend on machine speed.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import ForgotPasswordPage, { RESET_REQUESTED_MESSAGE } from "./forgot-password-page";

type Reply = { status?: number; body?: unknown };

/** Bodies POSTed to the request endpoint, in call order. Its length is the
 *  request count, which is what the "no second submit" test reads. */
let posted: unknown[] = [];

function mockApi(reply: Reply = {}) {
  posted = [];
  vi.stubGlobal(
    "fetch",
    vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://test.local");
      if (!url.pathname.endsWith("/auth/password-reset/request")) {
        throw new Error(`unexpected request to ${url.pathname}`);
      }
      posted.push(JSON.parse(String(init?.body ?? "null")));

      const status = reply.status ?? 202;
      return Promise.resolve({
        ok: status >= 200 && status < 300,
        status,
        json: () => Promise.resolve(reply.body ?? null),
      } as Response);
    })
  );
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ForgotPasswordPage />
    </MemoryRouter>
  );
}

function typeEmail(value: string) {
  fireEvent.change(screen.getByLabelText("이메일"), { target: { value } });
}

async function submit() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "재설정 링크 받기" }));
    await vi.advanceTimersByTimeAsync(0);
  });
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("ForgotPasswordPage", () => {
  it("says the same thing for a registered address as for any other", async () => {
    mockApi();
    renderPage();

    typeEmail("leader@church.org");
    await submit();

    // The wording must stay conditional. A message that asserts a mail was sent
    // would answer "does this account exist?" for any unauthenticated caller —
    // the exact question the server's uniform 202 refuses.
    expect(screen.getByText(RESET_REQUESTED_MESSAGE)).toBeTruthy();
    expect(RESET_REQUESTED_MESSAGE).toContain("있다면");
  });

  it("replaces the form once the request is accepted", async () => {
    mockApi();
    renderPage();

    typeEmail("leader@church.org");
    await submit();

    // Gone, not disabled: a second submit would spend one of five hourly slots
    // and tell the user nothing new.
    expect(screen.queryByLabelText("이메일")).toBeNull();
    expect(screen.queryByRole("button", { name: "재설정 링크 받기" })).toBeNull();
    expect(posted).toHaveLength(1);
  });

  it("does not announce success before the first submit", () => {
    mockApi();
    renderPage();

    expect(screen.queryByText(RESET_REQUESTED_MESSAGE)).toBeNull();
    expect(screen.getByLabelText("이메일")).toBeTruthy();
  });

  it("lowercases and trims the address before sending it", async () => {
    mockApi();
    renderPage();

    typeEmail("  Leader@Church.ORG  ");
    await submit();

    // Mirrors NormalizedEmail on the server, so the row the reset looks up is
    // the row a login with the same typing would reach.
    expect(posted).toEqual([{ email: "leader@church.org" }]);
  });

  it("keeps the form up and shows the reason when the rate limit is hit", async () => {
    const detail = "요청이 너무 많습니다. 잠시 후 다시 시도해 주세요.";
    mockApi({ status: 429, body: { detail } });
    renderPage();

    typeEmail("leader@church.org");
    await submit();

    // 429 arrives in the same {detail} shape as every other error, so the
    // limiter's own sentence has to reach the screen unaltered.
    expect(screen.getByText(detail)).toBeTruthy();
    // Still submittable: the user needs somewhere to retry from once the hour
    // is up, and the success panel would be a lie here.
    expect(screen.getByLabelText("이메일")).toBeTruthy();
    expect(screen.queryByText(RESET_REQUESTED_MESSAGE)).toBeNull();
  });

  it("does not show the English 'Not Found' when the feature is switched off", async () => {
    mockApi({ status: 404, body: { detail: "Not Found" } });
    renderPage();

    typeEmail("leader@church.org");
    await submit();

    // The link to this page is rendered unconditionally, but the endpoint only
    // exists while PASSWORD_RESET_ENABLED is set. An unmounted route answers
    // with a string `detail`, which normalizeApiError prefers over the fallback.
    expect(screen.queryByText("Not Found")).toBeNull();
    expect(screen.getByText(/사용할 수 없습니다/)).toBeTruthy();
    expect(screen.queryByText(RESET_REQUESTED_MESSAGE)).toBeNull();
  });

  it("does not reach the server when the address is empty", async () => {
    mockApi();
    renderPage();

    await submit();

    expect(posted).toHaveLength(0);
    expect(screen.queryByText(RESET_REQUESTED_MESSAGE)).toBeNull();
  });

  it("says a missing address once, under the field, with no alert repeating it", async () => {
    mockApi();
    renderPage();

    await submit();

    expect(screen.getByText("필수 입력 항목입니다.")).toBeTruthy();
    // The generic summary earns its place on a long form, where the field it
    // refers to may be off screen. Here the field is two lines up.
    expect(screen.queryByText("입력한 정보를 다시 확인해 주세요.")).toBeNull();
    expect(screen.queryByText("요청 실패")).toBeNull();
  });
});
