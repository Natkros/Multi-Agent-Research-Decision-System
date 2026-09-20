import { DecisionMatrixView } from "@/features/decision-matrix/DecisionMatrixView";

export default async function DecisionPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <DecisionMatrixView researchId={id} />;
}
