import { SourceExplorer } from "@/features/source-explorer/SourceExplorer";

export default async function SourcesPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <SourceExplorer researchId={id} />;
}
