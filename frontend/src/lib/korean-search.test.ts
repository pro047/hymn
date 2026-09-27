import { describe, expect, it } from "vitest";

import { matchesTitle } from "./korean-search";

describe("matchesTitle", () => {
  it("should match a plain substring", () => {
    expect(matchesTitle("주만 바라볼찌라", "바라")).toBe(true);
  });

  it("should ignore spaces on both sides", () => {
    expect(matchesTitle("은혜 아니면", "은혜아니")).toBe(true);
    expect(matchesTitle("은혜아니면", "은혜 아니")).toBe(true);
  });

  it("should ignore letter case", () => {
    expect(matchesTitle("Amazing Grace", "grace")).toBe(true);
  });

  it("should match a query of initial consonants alone", () => {
    expect(matchesTitle("주만 바라볼찌라", "ㅈㅁㅂ")).toBe(true);
    expect(matchesTitle("주만 바라볼찌라", "ㅂㄹㅂ")).toBe(true);
  });

  it("should match initials mixed with whole syllables", () => {
    expect(matchesTitle("주만 바라볼찌라", "주ㅁ바")).toBe(true);
  });

  it("should tell doubled initials apart from plain ones", () => {
    expect(matchesTitle("주만 바라볼찌라", "ㅉ")).toBe(true);
    expect(matchesTitle("주만 바라볼찌라", "ㅈㅈ")).toBe(false);
  });

  it("should not match initials out of order", () => {
    expect(matchesTitle("주만 바라볼찌라", "ㅁㅈ")).toBe(false);
  });

  it("should not let a whole syllable match a different one sharing its initial", () => {
    expect(matchesTitle("주만 바라볼찌라", "자")).toBe(false);
  });

  it("should find a title stored decomposed (NFD), as a macOS file name can be", () => {
    const decomposed = "구원으로 인도하는".normalize("NFD");
    expect(matchesTitle(decomposed, "ㄱㅇ")).toBe(true);
    expect(matchesTitle(decomposed, "구원")).toBe(true);
    expect(matchesTitle("구원으로 인도하는", "구원".normalize("NFD"))).toBe(true);
  });

  it("should match everything on an empty query", () => {
    expect(matchesTitle("아무 곡", "")).toBe(true);
    expect(matchesTitle("아무 곡", "   ")).toBe(true);
  });
});
