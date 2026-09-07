// No environment docblock on purpose: nothing here touches the DOM, and booting
// jsdom for it would cost the whole file a startup it never uses. Do not spell
// the docblock tag out even inside a comment — vitest matches the tag anywhere
// in the file, so naming it here would select an environment called "docblock".
import { describe, expect, it } from "vitest";

import {
  flattenPages,
  moveItem,
  padSlots,
  SLOTS_PER_PAGE,
  toOrderPayload,
  togglePageBreak,
  type ContiItem,
} from "./conti-order";

const song = (id: string, title: string, startsNewPage = false): ContiItem => ({
  score_id: id,
  title,
  starts_new_page: startsNewPage,
  image_url: null,
});

const A = song("a", "은혜");
const B = song("b", "믿음");
const C = song("c", "소망", true);
const D = song("d", "사랑");

const idsOf = (items: readonly ContiItem[]) => items.map((item) => item.score_id);

describe("flattenPages", () => {
  it("페이지들을 콘티 순서 하나로 펴야 한다", () => {
    // Arrange & Act
    const items = flattenPages([
      [A, B],
      [C],
    ]);

    // Assert
    expect(idsOf(items)).toEqual(["a", "b", "c"]);
  });

  it("페이지가 없으면 빈 배열이어야 한다", () => {
    expect(flattenPages([])).toEqual([]);
  });

  it("빈 페이지가 섞여 있어도 곡만 순서대로 담아야 한다", () => {
    // Arrange & Act — chunk_pages never emits an empty page today, but a
    // flatten that dropped or duplicated around one would go unnoticed.
    const items = flattenPages([[A], [], [B]]);

    // Assert
    expect(idsOf(items)).toEqual(["a", "b"]);
  });
});

describe("moveItem", () => {
  it("뒤의 곡을 앞으로 보내면 나머지가 뒤로 밀려야 한다", () => {
    // Arrange — the one case that tells insertion from a swap: swapping would
    // answer [c, b, a].
    const items = [A, B, C];

    // Act
    const next = moveItem(items, 2, 0);

    // Assert
    expect(idsOf(next)).toEqual(["c", "a", "b"]);
  });

  it("앞의 곡을 뒤로 보내면 사이의 곡들이 앞으로 당겨져야 한다", () => {
    // Arrange
    const items = [A, B, C, D];

    // Act
    const next = moveItem(items, 0, 2);

    // Assert — a swap would answer [c, b, a, d]
    expect(idsOf(next)).toEqual(["b", "c", "a", "d"]);
  });

  it("제자리 이동이면 같은 배열을 그대로 돌려줘야 한다", () => {
    // Arrange — callers use reference identity to skip the PATCH entirely.
    const items = [A, B, C];

    // Act & Assert
    expect(moveItem(items, 1, 1)).toBe(items);
  });

  it("인덱스가 범위 밖이면 같은 배열을 그대로 돌려줘야 한다", () => {
    // Arrange
    const items = [A, B, C];

    // Act & Assert
    expect(moveItem(items, -1, 0)).toBe(items);
    expect(moveItem(items, 0, -1)).toBe(items);
    expect(moveItem(items, items.length, 0)).toBe(items);
    expect(moveItem(items, 0, items.length)).toBe(items);
  });

  it("빈 배열이면 같은 배열을 그대로 돌려줘야 한다", () => {
    const items: ContiItem[] = [];

    expect(moveItem(items, 0, 0)).toBe(items);
  });

  it("원본 배열을 바꾸지 않아야 한다", () => {
    // Arrange
    const items = [A, B, C];

    // Act
    moveItem(items, 2, 0);

    // Assert
    expect(idsOf(items)).toEqual(["a", "b", "c"]);
  });
});

describe("padSlots", () => {
  it("모자란 칸을 null로 채워야 한다", () => {
    expect(padSlots([A], 2)).toEqual([A, null]);
  });

  it("칸 수를 넘기지 않으면 페이지 칸 수를 써야 한다", () => {
    // Arrange & Act — the default is the mirror of the backend constant.
    const slots = padSlots([A]);

    // Assert
    expect(slots).toEqual([A, null]);
    expect(SLOTS_PER_PAGE).toBe(2);
  });

  it("페이지가 칸 수보다 길면 곡을 버리지 않아야 한다", () => {
    // Arrange & Act — a server that starts sending 3-slot pages must show all
    // three, badly laid out, rather than silently hide the third song.
    const slots = padSlots([A, B, C], 2);

    // Assert
    expect(slots).toEqual([A, B, C]);
  });

  it("빈 페이지면 칸 수만큼 빈 칸이어야 한다", () => {
    expect(padSlots([], 2)).toEqual([null, null]);
  });
});

describe("toOrderPayload", () => {
  it("score_id와 starts_new_page만 순서대로 담아야 한다", () => {
    // Arrange & Act
    const payload = toOrderPayload([A, B]);

    // Assert — title/image_url must not travel; the server ignores them and
    // sending them would invite someone to start trusting them.
    expect(payload).toEqual([
      { score_id: "a", starts_new_page: false },
      { score_id: "b", starts_new_page: false },
    ]);
  });

  it("starts_new_page가 참인 곡은 참 그대로 실어야 한다", () => {
    // Arrange & Act — the page-break UI is out of scope, so this value is
    // relayed, never decided here. Flattening it to false would quietly undo
    // a break the leader set through some other path.
    const payload = toOrderPayload([C, A]);

    // Assert
    expect(payload).toEqual([
      { score_id: "c", starts_new_page: true },
      { score_id: "a", starts_new_page: false },
    ]);
  });

  it("곡이 없으면 빈 목록이어야 한다", () => {
    expect(toOrderPayload([])).toEqual([]);
  });
});

describe("togglePageBreak", () => {
  const item = (id: string, starts = false) => song(id, id, starts);

  it("꺼진 곡을 켜야 한다", () => {
    // Arrange
    const items = [item("a"), item("b"), item("c")];

    // Act
    const next = togglePageBreak(items, 1);

    // Assert
    expect(next.map((x) => x.starts_new_page)).toEqual([false, true, false]);
  });

  it("켜진 곡을 꺼야 한다", () => {
    // Arrange
    const items = [item("a"), item("b", true)];

    // Act & Assert
    expect(togglePageBreak(items, 1)[1].starts_new_page).toBe(false);
  });

  it("첫 곡은 같은 참조를 돌려줘야 한다", () => {
    // Arrange — chunk_pages ignores a break on the first item, so toggling it
    // would store a flag that changes nothing.
    const items = [item("a"), item("b")];

    // Act & Assert
    expect(togglePageBreak(items, 0)).toBe(items);
  });

  it("범위 밖 인덱스는 같은 참조를 돌려줘야 한다", () => {
    // Arrange
    const items = [item("a"), item("b")];

    // Act & Assert
    expect(togglePageBreak(items, 2)).toBe(items);
    expect(togglePageBreak(items, -1)).toBe(items);
  });

  it("원본을 바꾸지 않아야 한다", () => {
    // Arrange
    const items = [item("a"), item("b")];

    // Act
    togglePageBreak(items, 1);

    // Assert
    expect(items[1].starts_new_page).toBe(false);
  });
});
