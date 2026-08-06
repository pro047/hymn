import { afterEach, describe, expect, it, vi } from "vitest";

import { requestAuth } from "./auth";

const REQUEST = {
  url: "https://example.test/auth/signup",
  body: { email: "a@b.org" },
  failureMessage: "회원가입에 실패했습니다.",
  unreadableMessage: "회원가입은 완료됐지만 자동 로그인에 실패했습니다.",
  renderedFields: ["email", "phone"] as const,
};

function stubFetch(implementation: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(implementation));
}

function jsonResponse(status: number, body: unknown): Response {
  return { ok: status < 400, status, json: () => Promise.resolve(body) } as unknown as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("requestAuth", () => {
  it("토큰 쌍이 오면 저장 가능한 형태로 변환해야 한다", async () => {
    stubFetch(() =>
      Promise.resolve(
        jsonResponse(201, { tokens: { access_token: "access", refresh_token: "refresh" } })
      )
    );

    const outcome = await requestAuth(REQUEST);

    expect(outcome).toEqual({
      ok: true,
      tokens: { accessToken: "access", refreshToken: "refresh" },
    });
  });

  it("fetch 자체가 실패하면 네트워크 메시지를 보여줘야 한다", async () => {
    stubFetch(() => Promise.reject(new TypeError("Failed to fetch")));

    const outcome = await requestAuth(REQUEST);

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.error.formError).toBe("네트워크 연결을 확인한 뒤 다시 시도해 주세요.");
  });

  it("서버가 거부하면 detail을 정규화해 필드 오류로 넘겨야 한다", async () => {
    stubFetch(() =>
      Promise.resolve(
        jsonResponse(422, {
          detail: [{ type: "string_too_short", loc: ["body", "phone"], ctx: { min_length: 8 } }],
        })
      )
    );

    const outcome = await requestAuth(REQUEST);

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.error.fieldErrors.phone).toBe("최소 8자 이상 입력해 주세요.");
  });

  it("2xx인데 본문을 읽지 못하면 네트워크 실패로 보고하지 않아야 한다", async () => {
    // The account was already created; telling the user to check their
    // connection and retry would only earn them a 409 on the next submit.
    stubFetch(() =>
      Promise.resolve({
        ok: true,
        status: 201,
        json: () => Promise.reject(new Error("Unexpected end of JSON input")),
      } as unknown as Response)
    );

    const outcome = await requestAuth(REQUEST);

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.error.formError).toBe(REQUEST.unreadableMessage);
  });

  it("2xx인데 토큰 필드가 비어 있어도 같은 안내를 해야 한다", async () => {
    stubFetch(() => Promise.resolve(jsonResponse(201, { tokens: { access_token: "only-one" } })));

    const outcome = await requestAuth(REQUEST);

    expect(outcome.ok).toBe(false);
    if (outcome.ok) return;
    expect(outcome.error.formError).toBe(REQUEST.unreadableMessage);
  });
});
