import { SessionTabs } from "@/features/research-session/SessionTabs";

export default async function ResearchSessionLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return (
    <div>
      <SessionTabs researchId={id} />
      {children}
    </div>
  );
}
