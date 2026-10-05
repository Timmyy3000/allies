"use client";

import { DashboardUiPushExact } from "../../home/_exact/dashboard-ui-push-exact";

export default function DashboardUiPushPreview() {
  return (
    <div
      style={{
        width: "100%",
        height: "100dvh",
        overflow: "hidden",
        background: "#fff",
      }}
    >
      <DashboardUiPushExact />
    </div>
  );
}
