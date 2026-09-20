import { AgentTraceView } from "@/features/agent-trace/AgentTraceView";

export default async function TracePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <AgentTraceView researchId={id} />;
}
