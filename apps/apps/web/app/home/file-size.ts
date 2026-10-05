const UNITS = ["B", "KB", "MB", "GB"] as const;

const numberFormat = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });

export function formatFileSize(sizeBytes: number): string {
  if (!Number.isFinite(sizeBytes) || sizeBytes < 0) return "—";
  if (sizeBytes === 0) return "0 B";
  const exponent = Math.min(Math.floor(Math.log(sizeBytes) / Math.log(1024)), UNITS.length - 1);
  if (exponent === 0) return `${numberFormat.format(sizeBytes)} B`;
  const value = sizeBytes / 1024 ** exponent;
  return `${numberFormat.format(value)} ${UNITS[exponent]}`;
}
