// No environment docblock on purpose: nothing here touches the DOM, and booting
// jsdom for it would cost the whole file a startup it never uses. Do not spell
// the docblock tag out even inside a comment — vitest matches the tag anywhere
// in the file, so naming it here would select an environment called "docblock".
import { describe, expect, it } from "vitest";

import {
  moveInGrid,
  padSlots,
  SLOTS_PER_PAGE,
  songPositions,
  splitPageAt,
  toOrderPayload,
  withPageBreaks,
  type ContiItem,
  type ContiPages,
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

const at = (page: number, slot: number) => ({ page, slot });

/** The layout as ids, so a page split is visible in the expectation itself. */
const layoutOf = (pages: ContiPages) => pages.map((page) => page.map((item) => item.score_id));

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

describe("moveInGrid — 곡이 있는 칸에 놓으면 맞바꾼다", () => {
  it("다른 쪽의 곡과 자리를 맞바꿔야 한다", () => {
    // Arrange
    const pages: ContiPages = [[A, B], [C]];

    // Act — 소망(2쪽 첫 칸)을 은혜(1쪽 첫 칸) 자리로
    const next = moveInGrid(pages, at(1, 0), at(0, 0));

    // Assert — an insert would answer [[c, a], [b]]: 믿음이 2쪽으로 밀린다
    expect(layoutOf(next)).toEqual([["c", "b"], ["a"]]);
  });

  it("같은 쪽 안에서도 맞바꿔야 한다", () => {
    // Arrange
    const pages: ContiPages = [[A, B], [C]];

    // Act
    const next = moveInGrid(pages, at(0, 0), at(0, 1));

    // Assert
    expect(layoutOf(next)).toEqual([["b", "a"], ["c"]]);
  });

  it("맞바꿔도 쪽마다의 곡 수는 그대로여야 한다", () => {
    // Arrange — chunk_pages caps a page at SLOTS_PER_PAGE, so a move that grew
    // one could not be reproduced by the server and the preview would start
    // lying about the PDF.
    const pages: ContiPages = [[A, B], [C]];

    // Act
    const next = moveInGrid(pages, at(1, 0), at(0, 1));

    // Assert
    expect(next.map((page) => page.length)).toEqual([2, 1]);
  });
});

describe("moveInGrid — 빈 칸에 놓으면 옮긴다", () => {
  it("빈 칸으로 옮기면 그 쪽에 들어가고 떠난 쪽은 줄어야 한다", () => {
    // Arrange — 1쪽은 은혜 하나뿐이라 두 번째 칸이 비어 있다
    const pages: ContiPages = [[A], [B, C]];

    // Act — 믿음(2쪽 첫 칸)을 1쪽 빈 칸으로
    const next = moveInGrid(pages, at(1, 0), at(0, 1));

    // Assert
    expect(layoutOf(next)).toEqual([["a", "b"], ["c"]]);
  });

  it("마지막 곡을 앞 쪽 빈 칸으로 옮기면 빈 쪽은 사라져야 한다", () => {
    // Arrange — an empty page has no box to drop onto and would print as a
    // blank sheet.
    const pages: ContiPages = [[A], [B]];

    // Act
    const next = moveInGrid(pages, at(1, 0), at(0, 1));

    // Assert
    expect(layoutOf(next)).toEqual([["a", "b"]]);
  });

  it("빈 칸 인덱스가 그 쪽 길이보다 커도 끝에 붙여야 한다", () => {
    // Arrange — 2쪽은 소망 하나뿐이라 빈 칸이 slot 1 인데 그 쪽의 길이는 1 이다.
    // 인덱스가 길이를 넘어도 splice 가 끝에 붙이는 것에 기대는 자리 — 빈 칸은
    // 언제나 쪽의 꼬리라서 그 append 가 곧 노린 자리다.
    const pages: ContiPages = [[A, B], [C]];

    // Act
    const next = moveInGrid(pages, at(0, 0), at(1, 1));

    // Assert
    expect(layoutOf(next)).toEqual([["b"], ["c", "a"]]);
  });
});

describe("moveInGrid — 아무것도 안 바뀌면 같은 참조", () => {
  it("제자리에 놓으면 같은 참조를 돌려줘야 한다", () => {
    // Arrange — callers use reference identity to skip the PATCH entirely.
    const pages: ContiPages = [[A, B], [C]];

    // Act & Assert
    expect(moveInGrid(pages, at(0, 1), at(0, 1))).toBe(pages);
  });

  it("자기 쪽의 뒤 빈 칸으로 옮기면 같은 참조를 돌려줘야 한다", () => {
    // Arrange — 은혜를 빼고 같은 쪽 slot 1에 도로 넣으면 결과가 원본과 같다.
    // 참조로 걸러내지 않으면 아무것도 바뀌지 않은 PATCH가 나간다.
    const pages: ContiPages = [[A], [B]];

    // Act & Assert
    expect(moveInGrid(pages, at(0, 0), at(0, 1))).toBe(pages);
  });

  it("빈 칸에서 끌기 시작한 것은 같은 참조를 돌려줘야 한다", () => {
    // Arrange
    const pages: ContiPages = [[A], [B]];

    // Act & Assert
    expect(moveInGrid(pages, at(0, 1), at(1, 0))).toBe(pages);
  });

  it("없는 쪽을 가리키면 같은 참조를 돌려줘야 한다", () => {
    // Arrange
    const pages: ContiPages = [[A, B]];

    // Act & Assert
    expect(moveInGrid(pages, at(0, 0), at(3, 0))).toBe(pages);
    expect(moveInGrid(pages, at(3, 0), at(0, 0))).toBe(pages);
  });

  it("원본을 바꾸지 않아야 한다", () => {
    // Arrange
    const pages: ContiPages = [[A, B], [C]];

    // Act
    moveInGrid(pages, at(1, 0), at(0, 0));

    // Assert
    expect(layoutOf(pages)).toEqual([["a", "b"], ["c"]]);
  });
});

describe("songPositions", () => {
  it("곡만 콘티 순서대로 좌표를 매겨야 한다", () => {
    // Arrange & Act — the blank in page 1 slot 1 must not take a number, or
    // the up/down buttons would step into it.
    const positions = songPositions([[A], [B, C]]);

    // Assert
    expect(positions).toEqual([at(0, 0), at(1, 0), at(1, 1)]);
  });

  it("곡이 없으면 빈 목록이어야 한다", () => {
    expect(songPositions([])).toEqual([]);
  });
});

describe("withPageBreaks", () => {
  it("쪽마다 첫 곡만 나누기가 켜져야 한다", () => {
    // Arrange & Act
    const items = withPageBreaks([
      [A, B],
      [C, D],
    ]);

    // Assert — chunk_pages replays this: 소망의 켜진 플래그가 2쪽을 만들고,
    // 사랑은 그 쪽을 채운다.
    expect(items.map((item) => item.starts_new_page)).toEqual([false, false, true, false]);
    expect(items.map((item) => item.score_id)).toEqual(["a", "b", "c", "d"]);
  });

  it("첫 곡은 나누기가 켜져 있었어도 꺼야 한다", () => {
    // Arrange — C carries starts_new_page: true. chunk_pages ignores a break
    // on the first item and set_week_order refuses to store one, so relaying
    // it would write a value nothing reads.
    const items = withPageBreaks([[C, A]]);

    // Assert
    expect(items[0].starts_new_page).toBe(false);
  });

  it("한 곡짜리 쪽도 나누기로 표현해야 한다", () => {
    // Arrange & Act — 이 배치는 자동 분할로는 나오지 않는다. 두 번째 쪽의 첫
    // 곡에 플래그가 없으면 서버가 [a, b] 한 쪽으로 도로 붙인다.
    const items = withPageBreaks([[A], [B]]);

    // Assert
    expect(items.map((item) => item.starts_new_page)).toEqual([false, true]);
  });

  it("원본 곡을 바꾸지 않아야 한다", () => {
    // Arrange
    const pages: ContiPages = [[A], [C]];

    // Act
    withPageBreaks(pages);

    // Assert — C 는 모듈 전역이라 여기서 뒤집히면 다른 테스트가 함께 깨진다
    expect(A.starts_new_page).toBe(false);
    expect(C.starts_new_page).toBe(true);
  });

  it("곡이 없으면 빈 목록이어야 한다", () => {
    expect(withPageBreaks([])).toEqual([]);
  });
});

describe("splitPageAt", () => {
  it("쪽이 전부 꽉 차 있어도 경계를 만들 수 있어야 한다", () => {
    // Arrange — 곡 4개면 빈 칸이 하나도 없어 드롭으로는 나눌 수 없다.
    // 가위가 있어야만 편집이 되는 바로 그 배치.
    const pages: ContiPages = [
      [A, B],
      [C, D],
    ];

    // Act — 믿음 앞에서 자른다
    const items = splitPageAt(pages, at(0, 1));

    // Assert
    expect(items?.map((item) => item.score_id)).toEqual(["a", "b", "c", "d"]);
    expect(items?.map((item) => item.starts_new_page)).toEqual([false, true, true, false]);
  });

  it("자동으로 갈린 경계를 명시적 경계로 굳히지 않아야 한다", () => {
    // Arrange — 아무도 나누기를 켜지 않았는데 2쪽이 생긴 배치(2곡이 차서 끊겼다).
    // withPageBreaks 를 거치면 소망의 플래그가 켜져서, 한 번 누른 가위가
    // [은혜][믿음][소망,사랑] 로 두 번 자른 결과를 낸다.
    const pages: ContiPages = [
      [A, B],
      [song("c2", "소망"), D],
    ];

    // Act
    const items = splitPageAt(pages, at(0, 1));

    // Assert — 켜진 것은 믿음 하나뿐이다
    expect(items?.map((item) => item.starts_new_page)).toEqual([false, true, false, false]);
  });

  it("첫 곡 앞에서는 나눌 수 없어야 한다", () => {
    // Arrange — chunk_pages 가 첫 항목의 break 를 무시하므로 아무 일도 안 하는
    // 조작이 된다. 화면에도 그 자리엔 가위를 그리지 않는다.
    const pages: ContiPages = [[A, B]];

    // Act & Assert
    expect(splitPageAt(pages, at(0, 0))).toBeNull();
  });

  it("이미 나누기가 켜진 곡 앞에서는 null 이어야 한다", () => {
    // Arrange — C 는 starts_new_page: true 라 이미 쪽을 시작한다
    const pages: ContiPages = [[A], [C, D]];

    // Act & Assert
    expect(splitPageAt(pages, at(1, 0))).toBeNull();
  });

  it("빈 칸을 가리키면 null 이어야 한다", () => {
    // Arrange
    const pages: ContiPages = [[A], [B]];

    // Act & Assert
    expect(splitPageAt(pages, at(0, 1))).toBeNull();
  });

  it("원본을 바꾸지 않아야 한다", () => {
    // Arrange
    const pages: ContiPages = [[A, B]];

    // Act
    splitPageAt(pages, at(0, 1));

    // Assert
    expect(B.starts_new_page).toBe(false);
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
    // Arrange & Act — withPageBreaks decides the flag; this step only relays
    // it. Flattening it to false here would erase the page split on the way
    // out.
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
