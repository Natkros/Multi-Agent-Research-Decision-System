import type { ReactNode } from "react";
import type { Source } from "@/types";

/** Renders one citation marker (e.g. "[S3]") as a small link that jumps to
 * that source's anchor in the Sources section of the same report page. */
export function CitationLink({
  marker,
  sourceId,
  source,
}: {
  marker: string;
  sourceId?: string;
  source?: Source;
}) {
  const anchor = sourceId ? `#source-${sourceId}` : undefined;
  return (
    <a
      href={anchor}
      title={source ? source.title : sourceId}
      className="mx-0.5 inline-block rounded bg-blue-500/10 px-1 py-0.5 font-mono text-[11px] text-blue-300 hover:bg-blue-500/20"
    >
      {marker}
    </a>
  );
}

const CITATION_PATTERN = /\[S\d+\]/g;

/** Splits `text` on citation markers like "[S3]" and renders each as a
 * CitationLink using `citations` (marker -> source_id) and `sourcesById`
 * for the tooltip title. Falls back to plain text if no markers found. */
export function renderTextWithCitations(
  text: string,
  citations: Record<string, string>,
  sourcesById: Record<string, Source>,
): ReactNode[] {
  const parts = text.split(CITATION_PATTERN);
  const markers = text.match(CITATION_PATTERN) ?? [];
  const nodes: ReactNode[] = [];
  parts.forEach((part, i) => {
    if (part) nodes.push(<span key={`t-${i}`}>{part}</span>);
    const marker = markers[i];
    if (marker) {
      const sourceId = citations[marker];
      nodes.push(
        <CitationLink
          key={`c-${i}`}
          marker={marker}
          sourceId={sourceId}
          source={sourceId ? sourcesById[sourceId] : undefined}
        />,
      );
    }
  });
  return nodes;
}
