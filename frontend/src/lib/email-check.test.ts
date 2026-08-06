import { describe, expect, it } from "vitest";

import { looksLikeEmail, planEmailCheck, resolveEmailCheck } from "./email-check";
import { signupSchema } from "./validation/auth-schema";

const signupWith = (email: string) =>
  signupSchema.safeParse({
    name: "tester",
    email,
    password: "Password1",
    church: "Test Church",
    church_address: "Seoul",
    phone: "01012345678",
    agreed_terms: true as const,
  });

/** The page keeps a Map; these tests build the same thing literally. */
const cacheOf = (entries: Record<string, boolean>) => new Map(Object.entries(entries));

describe("looksLikeEmail", () => {
  it("다듬으면 형식이 맞는 값이면 조회를 허용해야 한다", () => {
    expect(looksLikeEmail("  Tester@Example.COM  ")).toBe(true);
  });

  it.each(["", "a", "tester@", "a@b"])("%s 는 조회하지 않아야 한다", (raw) => {
    expect(looksLikeEmail(raw)).toBe(false);
  });

  // The divergences found by cross-running zod and pydantic over 62 inputs. Until
  // M3 these were pinned against signupSchema, which rejected them and so made
  // the addresses unregisterable; the rule moved here, where a false only means
  // "no automatic duplicate check for this one".
  it.each(["a@b.c", "한글@example.com", "a@한글.com", "a@example.c"])(
    "서버가 받아주는 주소 %s 는 조회를 건너뛰더라도 가입은 막지 않아야 한다",
    (email) => {
      expect(looksLikeEmail(email)).toBe(false);
      expect(signupWith(email).success).toBe(true);
    }
  );

  it("도메인이 하이픈으로 끝나는 주소는 통과시켜 서버 판정에 맡긴다", () => {
    // Known looser-than-server case: this reaches check-email and comes back 422,
    // which resolveEmailCheck reports as unknown rather than as an error.
    expect(looksLikeEmail("a@example-.com")).toBe(true);
  });
});

describe("planEmailCheck", () => {
  it("형식이 덜 갖춰진 값이면 조회 없이 미확인이어야 한다", () => {
    const plan = planEmailCheck("teste", cacheOf({}));

    expect(plan).toEqual({ action: "skip", status: "unknown" });
  });

  it("처음 보는 주소면 조회하고 확인중으로 표시해야 한다", () => {
    const plan = planEmailCheck("tester@example.com", cacheOf({}));

    expect(plan).toEqual({ action: "query", status: "checking", key: "tester@example.com" });
  });

  it("이미 답을 받은 주소면 재조회하지 않아야 한다", () => {
    const plan = planEmailCheck("tester@example.com", cacheOf({ "tester@example.com": false }));

    expect(plan).toEqual({ action: "reuse", status: "taken", key: "tester@example.com" });
  });

  it("사용 가능으로 캐시된 주소도 재조회하지 않아야 한다", () => {
    const plan = planEmailCheck("tester@example.com", cacheOf({ "tester@example.com": true }));

    expect(plan).toEqual({ action: "reuse", status: "available", key: "tester@example.com" });
  });

  it("대소문자와 공백만 다른 값은 같은 캐시 항목을 써야 한다", () => {
    // The server lowercases before looking up, so treating these as two addresses
    // would burn two of the ten lookups a minute on one answer.
    const plan = planEmailCheck(" Tester@Example.COM ", cacheOf({ "tester@example.com": false }));

    expect(plan).toEqual({ action: "reuse", status: "taken", key: "tester@example.com" });
  });
});

describe("resolveEmailCheck", () => {
  it("응답이 도착했을 때 값이 그대로면 결과를 반영해야 한다", () => {
    const resolution = resolveEmailCheck("tester@example.com", "tester@example.com", false);

    expect(resolution).toEqual({ apply: true, status: "taken" });
  });

  it("사용 가능하다는 응답이면 사용가능으로 반영해야 한다", () => {
    const resolution = resolveEmailCheck("tester@example.com", "tester@example.com", true);

    expect(resolution).toEqual({ apply: true, status: "available" });
  });

  it("응답을 기다리는 사이 값이 바뀌었으면 반영하지 않아야 한다", () => {
    // The bug this exists for: a slow answer about the old address arrives after
    // the user has typed a new one and stamps its verdict on the wrong value.
    const resolution = resolveEmailCheck("tester@example.com", "other@example.com", false);

    expect(resolution).toEqual({ apply: false });
  });

  it("값이 다듬기 전에만 다르면 같은 값으로 봐야 한다", () => {
    const resolution = resolveEmailCheck("tester@example.com", " Tester@Example.COM ", false);

    expect(resolution).toEqual({ apply: true, status: "taken" });
  });

  it("서버가 답하지 못했으면 오류 대신 미확인으로 되돌려야 한다", () => {
    // 429, or a 422 for an address the trigger accepted and EmailStr did not.
    // Neither is the user's mistake to fix, and the submit still has the 409.
    const resolution = resolveEmailCheck("a@example-.com", "a@example-.com", null);

    expect(resolution).toEqual({ apply: true, status: "unknown" });
  });

  it("답하지 못한 응답이 옛 값에 대한 것이면 그것도 무시해야 한다", () => {
    const resolution = resolveEmailCheck("a@example-.com", "other@example.com", null);

    expect(resolution).toEqual({ apply: false });
  });
});
