// Type-only shim for card.jsx — see input.d.ts for why.
import type { ComponentProps, ReactElement } from "react";

declare function Card(props: ComponentProps<"div">): ReactElement;
declare function CardHeader(props: ComponentProps<"div">): ReactElement;
declare function CardFooter(props: ComponentProps<"div">): ReactElement;
declare function CardTitle(props: ComponentProps<"h3">): ReactElement;
declare function CardDescription(props: ComponentProps<"p">): ReactElement;
declare function CardContent(props: ComponentProps<"div">): ReactElement;

export { Card, CardHeader, CardFooter, CardTitle, CardDescription, CardContent };
