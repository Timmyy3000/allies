import {
  Book, Calendar, Code, Cpu, DocumentText, Eye, Gallery, GlobalSearch,
  MagicStar, More, People, SearchNormal, TaskSquare, Video, VolumeHigh,
  type Icon,
} from "iconsax-reactjs";

// Temporary Iconsax Bulk assets; replace this map with the designer's licensed set.
const icons: Record<string, Icon> = {
  web_search: GlobalSearch,
  web_extract: GlobalSearch,
  browser_navigate: GlobalSearch,
  browser_interact: GlobalSearch,
  search_files: SearchNormal,
  read_file: DocumentText,
  write_file: DocumentText,
  patch: DocumentText,
  terminal: Code,
  execute_code: Code,
  image_generate: Gallery,
  video_generate: Video,
  text_to_speech: VolumeHigh,
  vision_analyze: Eye,
  session_search: SearchNormal,
  memory_remember: Cpu,
  memory_recall: Cpu,
  memory: Cpu,
  skills_list: Book,
  skill_view: Book,
  skill_manage: Book,
  todo: TaskSquare,
  cronjob: Calendar,
  delegate_task: People,
  unknown: MagicStar,
};

export function ActivityIcon({ kind, tone }: { kind?: string | null; tone?: "accent" | "muted" | "default" }) {
  const iconKind = kind ?? "unknown";
  const Icon = Object.prototype.hasOwnProperty.call(icons, iconKind) ? icons[iconKind] : More;
  return <Icon variant="Bulk" size={18} color={tone === "muted" ? "var(--text-secondary)" : "var(--chat-accent)"} aria-hidden="true" />;
}
