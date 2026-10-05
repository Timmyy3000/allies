import Image from "next/image";
import styles from "./loading-skeletons.module.css";

export function Skeleton({ className = "" }: { className?: string }) {
  return <span className={`${styles.bone} ${className}`} aria-hidden="true" />;
}

export function QuietSplash({ label }: { label: string }) {
  return (
    <main className={styles.splash} role="status" aria-label={label}>
      <Image className={styles.splashMark} src="/allies-icon.svg" alt="" width={44} height={44} priority />
    </main>
  );
}

function RowSkeleton() {
  return (
    <div className={styles.row}>
      <Skeleton className={styles.avatar} />
      <span className={styles.rowCopy}>
        <Skeleton className={styles.lineShort} />
        <Skeleton className={styles.lineLong} />
      </span>
    </div>
  );
}

export function HomeSkeleton({ label = "Loading your Allies" }: { label?: string }) {
  return (
    <main className={styles.home} role="status" aria-label={label}>
      <aside className={styles.homeList}>
        <Skeleton className={styles.search} />
        {Array.from({ length: 5 }, (_, index) => <RowSkeleton key={index} />)}
      </aside>
      <section className={styles.homePane} aria-hidden="true" />
    </main>
  );
}

export function SettingsSkeleton({ label }: { label: string }) {
  return (
    <main className={styles.settings} role="status" aria-label={label}>
      <div className={styles.settingsShell}>
        <div className={styles.settingsHeader}>
          <Skeleton className={styles.back} />
          <Skeleton className={styles.title} />
        </div>
        <Skeleton className={styles.hero} />
        {Array.from({ length: 3 }, (_, index) => <Skeleton key={index} className={styles.section} />)}
      </div>
    </main>
  );
}

export function MessagesSkeleton() {
  return (
    <div className={styles.messages} role="status" aria-label="Loading conversation">
      <Skeleton className={`${styles.bubble} ${styles.bubbleIn}`} />
      <Skeleton className={`${styles.bubble} ${styles.bubbleOut}`} />
      <Skeleton className={`${styles.bubble} ${styles.bubbleIn} ${styles.bubbleTall}`} />
      <Skeleton className={`${styles.bubble} ${styles.bubbleOut} ${styles.bubbleNarrow}`} />
    </div>
  );
}
