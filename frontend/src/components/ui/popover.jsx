import * as React from "react"
import * as PopoverPrimitive from "@radix-ui/react-popover"

import { cn } from "../../lib/utils"

const Popover = PopoverPrimitive.Root
const PopoverTrigger = PopoverPrimitive.Trigger

const PopoverContent = React.forwardRef(function PopoverContent(
  { className, align = "center", sideOffset = 4, ...props },
  ref
) {
  return (
    <PopoverPrimitive.Portal>
      <PopoverPrimitive.Content
        ref={ref}
        align={align}
        sideOffset={sideOffset}
        className={cn(
          "z-50 w-72 rounded-md border border-stone-200 bg-white p-4 text-stone-950 shadow-lg outline-none",
          className
        )}
        {...props}
      />
    </PopoverPrimitive.Portal>
  )
})

export { Popover, PopoverTrigger, PopoverContent }
