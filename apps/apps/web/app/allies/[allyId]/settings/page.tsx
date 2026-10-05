import { AllySettingsClient } from "./settings-client";

export default async function AllySettingsPage({ params }: { params: Promise<{ allyId: string }> }) {
  const { allyId } = await params;
  return <AllySettingsClient allyId={allyId} />;
}
