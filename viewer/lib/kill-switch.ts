// Mirrors the Python helper in tools/check_status.py.
// Reads ENVISION_CURATOR_ENABLED from the server-side environment.

function truthy(value: string | undefined, defaultVal = true): boolean {
  if (value === undefined || value === '') return defaultVal;
  return ['1', 'true', 'yes', 'on', 'y', 't'].includes(
    value.trim().toLowerCase()
  );
}

export function isCuratorEnabled(): boolean {
  return truthy(process.env.ENVISION_CURATOR_ENABLED, true);
}
