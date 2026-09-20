import { SourceExplorer } from "@/features/source-explorer/SourceExplorer";

export default function SourcesPage({ params }: { params: { id: string } }) {
  return <SourceExplorer researchId={params.id} />;
}
