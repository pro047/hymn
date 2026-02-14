import { cn } from "../../lib/utils"

function Separator({ className, orientation = "horizontal", ...props }) {
  return (
    <div
      role="separator"
      data-orientation={orientation}
      className={cn(
        "shrink-0 bg-stone-200",
        orientation === "horizontal" ? "h-px w-full" : "h-full w-px",
        className
      )}
      {...props}
    />
  )
}

export { Separator }
