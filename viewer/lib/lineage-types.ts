/** Shared lineage graph types — safe for client `import type` / constants only. */

export const MIN_SHADOW_EVALS = 20;

export type LineageStatus =
  | 'candidate'
  | 'shadow'
  | 'promoted'
  | 'archived';

export type GenerationMethod = 'manual' | 'mutated' | 'generated';

export type LineageNodeData = {
  id: string;
  skillId: string;
  parentSkillId: string | null;
  version: number | null;
  generationMethod: GenerationMethod;
  status: LineageStatus;
  displayName: string;
  plainDescription: string;
  brier: number | null;
  hits: number;
  falsePositives: number;
  misses: number;
  emitted: number;
  shadowEvalCount: number | null;
  brierByVersion: { version: number; brier: number }[];
};

export type LineageEdgeData = {
  id: string;
  source: string;
  target: string;
};

export type LineageGraph = {
  nodes: LineageNodeData[];
  edges: LineageEdgeData[];
  orphanProposalCount: number;
};
