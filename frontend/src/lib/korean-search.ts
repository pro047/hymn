// Initial consonants in syllable-block order: a syllable's initial is
// INITIALS[(code - 0xac00) / 588], since each initial covers 21 vowels x 28
// finals.
const INITIALS = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
const SYLLABLE_FIRST = 0xac00;
const SYLLABLE_LAST = 0xd7a3;
const SYLLABLES_PER_INITIAL = 588;

function initialOf(char: string): string | null {
  const code = char.charCodeAt(0);
  if (code < SYLLABLE_FIRST || code > SYLLABLE_LAST) return null;
  return INITIALS[Math.floor((code - SYLLABLE_FIRST) / SYLLABLES_PER_INITIAL)];
}

// A typed initial stands for any syllable that starts with it; anything else
// has to be the same character.
function charMatches(typed: string, actual: string): boolean {
  if (typed === actual) return true;
  return INITIALS.includes(typed) && initialOf(actual) === typed;
}

// NFC first: a title can arrive decomposed (a macOS file name used as the
// title), and then "구" is two code points, ᄀ + ᅮ, that neither equal a
// typed "구" nor fall in the syllable range an initial is read from.
const normalize = (text: string) => text.normalize("NFC").replace(/\s+/g, "").toLowerCase();

/**
 * Whether `query` finds `title`: a contiguous run of characters, spaces and
 * case ignored, where an initial consonant ("ㅈㅁㅂ") matches any syllable it
 * begins -- so "ㅈㅁㅂ", "주만바", and "주ㅁ바" all find "주만 바라볼찌라".
 */
export function matchesTitle(title: string, query: string): boolean {
  const typed = [...normalize(query)];
  if (typed.length === 0) return true;
  const actual = [...normalize(title)];
  for (let start = 0; start + typed.length <= actual.length; start += 1) {
    if (typed.every((char, i) => charMatches(char, actual[start + i]))) return true;
  }
  return false;
}
