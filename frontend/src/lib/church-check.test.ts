import { describe, expect, it } from "vitest";

import {
  CHURCH_NAME_MIN_LOOKUP_LENGTH,
  looksLikeChurchName,
  planChurchCheck,
  resolveChurchCheck,
} from "./church-check";

/** The page keeps a Map; these tests build the same thing literally. */
const cacheOf = (entries: Record<string, boolean>) => new Map(Object.entries(entries));

describe("looksLikeChurchName", () => {
  it("공백을 걷어낸 길이가 기준을 넘으면 조회를 허용해야 한다", () => {
    expect(looksLikeChurchName("  확인교회  ")).toBe(true);
  });

  it("공백뿐인 값은 조회하지 않아야 한다", () => {
    expect(looksLikeChurchName("    ")).toBe(false);
  });

  it("기준 길이보다 짧으면 조회하지 않아야 한다", () => {
    // Derived from the constant rather than written out, so raising the bar
    // does not silently leave this asserting the old one.
    expect(looksLikeChurchName("가".repeat(CHURCH_NAME_MIN_LOOKUP_LENGTH - 1))).toBe(false);
    expect(looksLikeChurchName("가".repeat(CHURCH_NAME_MIN_LOOKUP_LENGTH))).toBe(true);
  });
});

describe("planChurchCheck", () => {
  it("아직 짧은 값이면 조회 없이 미확인이어야 한다", () => {
    const plan = planChurchCheck("가", cacheOf({}));

    expect(plan).toEqual({ action: "skip", status: "unknown" });
  });

  it("처음 보는 이름이면 조회하고 확인중으로 표시해야 한다", () => {
    const plan = planChurchCheck("확인교회", cacheOf({}));

    expect(plan).toEqual({ action: "query", status: "checking", key: "확인교회" });
  });

  it("이미 답을 받은 이름이면 요청 없이 그 답을 다시 써야 한다", () => {
    expect(planChurchCheck("확인교회", cacheOf({ 확인교회: true }))).toEqual({
      action: "reuse",
      status: "existing",
      key: "확인교회",
    });
    expect(planChurchCheck("새교회", cacheOf({ 새교회: false }))).toEqual({
      action: "reuse",
      status: "new",
      key: "새교회",
    });
  });

  it("앞뒤 공백만 다른 이름은 같은 캐시 항목을 써야 한다", () => {
    const plan = planChurchCheck("  확인교회  ", cacheOf({ 확인교회: true }));

    expect(plan).toEqual({ action: "reuse", status: "existing", key: "확인교회" });
  });

  it("대소문자가 다르면 다른 교회로 다뤄야 한다", () => {
    // churches.name is compared exactly by the server. Folding case here would
    // report a church as existing that the signup would then try to create.
    const plan = planChurchCheck("Grace Church", cacheOf({ "grace church": true }));

    expect(plan).toEqual({ action: "query", status: "checking", key: "Grace Church" });
  });
});

describe("resolveChurchCheck", () => {
  it("답이 도착했을 때 입력값이 그대로면 반영해야 한다", () => {
    expect(resolveChurchCheck("확인교회", "확인교회", true)).toEqual({
      apply: true,
      status: "existing",
    });
    expect(resolveChurchCheck("새교회", "  새교회  ", false)).toEqual({
      apply: true,
      status: "new",
    });
  });

  it("답이 도착했을 때 입력값이 이미 바뀌었으면 버려야 한다", () => {
    // The guard that keeps a slow answer about an old name from deciding which
    // fields are shown for a newer one.
    expect(resolveChurchCheck("확인교회", "다른교회", true)).toEqual({ apply: false });
  });

  it("서버가 답을 주지 못했으면 미확인으로 되돌려야 한다", () => {
    expect(resolveChurchCheck("확인교회", "확인교회", null)).toEqual({
      apply: true,
      status: "unknown",
    });
  });
});
