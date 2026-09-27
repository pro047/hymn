import { useMemo, useState } from "react";
import { Check } from "lucide-react";

import { Input } from "../../../components/ui/input";
import { matchesTitle } from "../../../lib/korean-search";

// Picking songs for a Sunday favors the ones sung most, so the most used lead
// and the more recently used break a tie. The library tab keeps its own
// newest-first order; this re-sorts the list it already fetched.
function byMostUsed(a, b) {
  if (b.use_count !== a.use_count) return b.use_count - a.use_count;
  return String(b.last_used_at ?? "").localeCompare(String(a.last_used_at ?? ""));
}

export default function SavedScorePicker({ scores, selectedId, onSelect }) {
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    return [...scores].filter((score) => matchesTitle(score.title, query)).sort(byMostUsed);
  }, [scores, query]);

  if (scores.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-stone-300 p-4 text-sm text-stone-500">
        보관함이 비어 있습니다.
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <Input
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="제목 또는 초성으로 찾기 (예: ㅈㅁㅂ)"
        aria-label="보관함 악보 검색"
      />
      {visible.length === 0 ? (
        <p className="py-6 text-center text-sm text-stone-500">검색 결과가 없습니다.</p>
      ) : (
        <div className="grid max-h-96 grid-cols-2 gap-3 overflow-y-auto pr-1 sm:grid-cols-3">
          {visible.map((score) => {
            const selected = score.score_id === selectedId;
            return (
              <button
                key={score.score_id}
                type="button"
                aria-pressed={selected}
                onClick={() => onSelect(score.score_id)}
                className={`relative overflow-hidden rounded-lg border bg-white text-left transition ${
                  selected
                    ? "border-stone-900 ring-2 ring-stone-900"
                    : "border-stone-200 hover:border-stone-400"
                }`}
              >
                {/* Sheets are portrait and are recognized by their top -- the
                    title and first line -- so the crop keeps the top. */}
                <div className="aspect-[3/4] overflow-hidden bg-stone-100">
                  <img
                    src={score.download_url ?? score.file_url}
                    alt={score.title}
                    loading="lazy"
                    className="h-full w-full object-cover object-top"
                  />
                </div>
                <div className="border-t border-stone-200 px-2 py-1.5">
                  <p
                    data-testid="saved-score-title"
                    className="truncate text-sm font-medium text-stone-900"
                  >
                    {score.title}
                  </p>
                  <p className="text-xs text-stone-500">사용 {score.use_count}회</p>
                </div>
                {selected ? (
                  <span className="absolute right-1.5 top-1.5 flex h-6 w-6 items-center justify-center rounded-full bg-stone-900 text-white">
                    <Check className="h-4 w-4" />
                  </span>
                ) : null}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
