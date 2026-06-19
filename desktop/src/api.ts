// 後端 Tauri 指令的型別化封裝
import { convertFileSrc, invoke } from "@tauri-apps/api/core";

export { convertFileSrc };

export interface NextSession {
  today: string;
  is_trading_day: boolean;
  next_session: string;
}

export interface Status {
  date: string;
  snapshot: boolean;
  brief: boolean;
  script: boolean;
  report: boolean;
  video: boolean;
  publish: boolean;
  cover: boolean;
  published: boolean | null;
  video_id: string | null;
}

export type ArtifactKind = "snapshot" | "brief" | "script" | "report" | "publish";
export type Step = "fetch" | "research" | "assemble" | "publish" | "run";

export const listDates = () => invoke<string[]>("list_dates");
export const getStatus = (date: string) => invoke<Status>("get_status", { date });
export const readArtifact = (date: string, kind: ArtifactKind) =>
  invoke<string>("read_artifact", { date, kind });
export const videoPath = (date: string) => invoke<string | null>("video_path", { date });
export const coverPath = (date: string) => invoke<string | null>("cover_path", { date });
export const openPath = (path: string) => invoke<void>("open_path", { path });
export const openRel = (rel: string) => invoke<void>("open_rel", { rel });
export const nextSession = () => invoke<NextSession>("next_session");

export const runStep = (step: Step, date: string, dryrun: boolean, approve: boolean) =>
  invoke<void>("run_step", { step, date: date || null, dryrun, approve });

// 講稿 / brief 的最小型別(只取畫面要用的欄位)
export interface Segment {
  vo: string;
  chart_id: string | null;
  headline: string | null;
  title: string | null;
  tag: string | null;
  t_start: number;
  duration: number;
}
export interface ScriptDoc {
  segments: Segment[];
  charts: { id: string; module: string }[];
  coverage_gaps?: string[];
}
export interface BriefItem {
  headline: string;
  horizon: string;
  vs_thesis: string;
  materiality: number;
  confidence: string;
  audience_value: string;
}
export interface BriefDoc {
  date: string;
  items: BriefItem[];
  catalysts?: string[];
  regime: Record<string, string>;
  thesis_delta: { changed: boolean; summary?: string; horizon?: string };
  lead_horizon: string;
}
