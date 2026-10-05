import { notFound } from "next/navigation";
import { TransitionsLab } from "./transitions-lab";

export default function TransitionsPage() {
  if (process.env.NODE_ENV !== "development") notFound();
  return <TransitionsLab />;
}
