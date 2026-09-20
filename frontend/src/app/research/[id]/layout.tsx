import { SessionTabs } from "@/features/research-session/SessionTabs";

export default function ResearchSessionLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: { id: string };
}) {
  return (
    <div>
      <SessionTabs researchId={params.id} />
      {children}
    </div>
  );
}
