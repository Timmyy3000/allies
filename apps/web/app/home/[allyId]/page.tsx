import { HomeWorkspace } from "../home-workspace";

export default async function AllyHomePage({ params }: { params: Promise<{ allyId: string }> }) {
  const { allyId } = await params;
  return <HomeWorkspace selectedAllyId={allyId} />;
}
