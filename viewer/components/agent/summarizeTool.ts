/** Client-side one-line tool summaries for the agent transcript. */

function asRecord(v: unknown): Record<string, unknown> | null {
  return v && typeof v === 'object' && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

function regionFromBbox(input: unknown): string | null {
  const rec = asRecord(input);
  const bbox = rec?.bbox;
  if (Array.isArray(bbox) && bbox.length === 4) {
    const [w, s, e, n] = bbox.map(Number);
    if ([w, s, e, n].every((x) => Number.isFinite(x))) {
      const lon = (w + e) / 2;
      const lat = (s + n) / 2;
      const ns = lat >= 0 ? 'N' : 'S';
      const ew = lon >= 0 ? 'E' : 'W';
      return `${Math.abs(lat).toFixed(0)}°${ns} ${Math.abs(lon).toFixed(0)}°${ew}`;
    }
  }
  return null;
}

function sourceCounts(output: unknown): string | null {
  const o = asRecord(output);
  if (!o) return null;

  const scoped = o.scoped_counts;
  if (Array.isArray(scoped) && scoped.length) {
    const bySource = new Map<string, number>();
    for (const row of scoped) {
      const r = asRecord(row);
      if (!r) continue;
      const source = String(r.source ?? 'src');
      const n = Number(r.count ?? 0);
      bySource.set(source, (bySource.get(source) ?? 0) + (Number.isFinite(n) ? n : 0));
    }
    if (bySource.size) {
      return [...bySource.entries()]
        .slice(0, 4)
        .map(([src, n]) => `${src} ${n}`)
        .join(', ');
    }
  }

  const catalog = o.catalog;
  if (Array.isArray(catalog) && catalog.length) {
    const bySource = new Map<string, number>();
    for (const row of catalog) {
      const r = asRecord(row);
      if (!r) continue;
      const source = String(r.source ?? 'src');
      const n = Number(r.row_count ?? 0);
      bySource.set(source, (bySource.get(source) ?? 0) + (Number.isFinite(n) ? n : 0));
    }
    if (bySource.size) {
      return [...bySource.entries()]
        .slice(0, 4)
        .map(([src, n]) => `${src} ${n}`)
        .join(', ');
    }
  }
  return null;
}

export function summarizeTool(
  tool: string,
  input: unknown,
  output: unknown
): string {
  const inp = asRecord(input);
  const out = asRecord(output);

  switch (tool) {
    case 'inspect_signals': {
      const region = regionFromBbox(input);
      const counts = sourceCounts(output);
      if (region && counts) return `${region} · ${counts}`;
      if (counts) return counts;
      if (region) return region;
      return 'inspect_signals';
    }
    case 'list_skills': {
      const skills = out?.skills;
      const n = Array.isArray(skills)
        ? skills.length
        : Array.isArray(output)
          ? output.length
          : typeof out?.count === 'number'
            ? out.count
            : null;
      return n != null ? `listed ${n} skills` : 'listed skills';
    }
    case 'run_skill': {
      const skillId = String(inp?.skill_id ?? 'skill');
      const count =
        typeof out?.count === 'number'
          ? out.count
          : Array.isArray(out?.candidates)
            ? out.candidates.length
            : null;
      return count != null
        ? `${skillId} → ${count} candidates`
        : `${skillId} → candidates`;
    }
    case 'emit': {
      const selected = Array.isArray(inp?.selected) ? inp.selected.length : null;
      const emitted =
        typeof out?.count === 'number'
          ? out.count
          : Array.isArray(out?.emitted_ids)
            ? out.emitted_ids.length
            : null;
      if (emitted != null && selected != null) {
        return `selected ${emitted} of ${selected} candidates`;
      }
      if (emitted != null) return `selected ${emitted} candidates`;
      if (selected != null) return `selected ${selected} candidates`;
      return 'emit';
    }
    case 'mutate_skill': {
      const skillId = String(inp?.skill_id ?? out?.skill_id ?? 'skill');
      return `mutate ${skillId}`;
    }
    case 'generate_skill': {
      const cls = String(
        inp?.disaster_class ?? out?.disaster_class ?? 'skill'
      );
      return `generate ${cls}`;
    }
    case 'inspect_forecasts': {
      const skillId = String(inp?.skill_id ?? out?.skill_id ?? 'skill');
      const n = typeof out?.count === 'number' ? out.count : null;
      return n != null
        ? `inspect ${skillId} · ${n} forecasts`
        : `inspect ${skillId}`;
    }
    default:
      return tool || 'tool';
  }
}
