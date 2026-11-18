import { EllipsisVertical } from "lucide-react";
import { useRef, useState } from "react";

import { Button } from "../../../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../../../components/ui/card";
import { Popover, PopoverContent, PopoverTrigger } from "../../../components/ui/popover";

// Every song the church has is here, so there is nothing to take out: deleting
// a song would take it off every Sunday that used it.
export default function SavedScoresCard({ scores, onApplyRequest, onQuickUpload, onEditRequest }) {
  const fileInputRef = useRef(null);
  // One menu open at a time, closed again once 수정 hands the song over.
  const [menuFor, setMenuFor] = useState(null);

  const handleFileChange = (event) => {
    const selectedFile = event.target.files?.[0] || null;
    if (selectedFile) {
      onQuickUpload?.(selectedFile);
    }
    event.target.value = "";
  };

  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <div>
          <CardTitle>악보 보관함</CardTitle>
          <p className="mt-1 text-xs text-stone-500">
            교회의 모든 곡이 여기 있습니다. 골라서 주차에 반영하거나 새 악보를 추가합니다.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <input
            ref={fileInputRef}
            className="hidden"
            type="file"
            accept="image/*"
            onChange={handleFileChange}
          />
          <Button type="button" size="sm" onClick={() => fileInputRef.current?.click()}>
            업로드
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {scores.length === 0 ? (
          <div className="rounded-md border border-dashed border-stone-300 p-4 text-sm text-stone-500">
            아직 올린 악보가 없습니다.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 xl:grid-cols-5">
            {scores.map((score) => (
              <div key={score.song_id} className="group relative min-w-0">
                <button
                  type="button"
                  className="block w-full text-left"
                  onClick={() => onApplyRequest(score)}
                >
                  <div className="overflow-hidden rounded-xl border border-stone-200 bg-stone-50 shadow-sm transition group-hover:border-stone-300 group-hover:shadow-md">
                    <div className="aspect-square overflow-hidden bg-stone-100">
                      <img
                        src={score.download_url ?? score.file_url}
                        alt={score.title}
                        className="h-full w-full object-cover transition duration-200 group-hover:scale-[1.02]"
                      />
                    </div>
                    <div className="border-t border-stone-200 bg-white px-3 py-2">
                      <p className="truncate text-sm font-medium text-stone-900">{score.title}</p>
                    </div>
                  </div>
                </button>
                {/* A sibling of the tile, not a child: a button inside a button is
                    invalid HTML and a click would bubble into onApplyRequest.
                    Shown on hover or focus where there is a pointer, always on
                    touch screens, which have no hover to reveal it with. */}
                {onEditRequest ? (
                  <Popover
                    open={menuFor === score.song_id}
                    onOpenChange={(open) => setMenuFor(open ? score.song_id : null)}
                  >
                    <PopoverTrigger asChild>
                      <button
                        type="button"
                        aria-label={`${score.title} 메뉴`}
                        className="absolute right-2 top-2 inline-flex h-8 w-8 items-center justify-center rounded-md bg-white/90 text-stone-600 opacity-0 shadow-sm transition hover:bg-white hover:text-stone-900 focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100"
                      >
                        <EllipsisVertical className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </PopoverTrigger>
                    <PopoverContent align="end" className="w-32 p-1">
                      <button
                        type="button"
                        aria-label={`${score.title} 수정`}
                        className="w-full rounded px-3 py-2 text-left text-sm text-stone-800 hover:bg-stone-100"
                        onClick={() => {
                          setMenuFor(null);
                          onEditRequest(score);
                        }}
                      >
                        수정
                      </button>
                    </PopoverContent>
                  </Popover>
                ) : null}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
