export type SparklinePoint = { version: number; brier: number };

export type SparklineProps = {
  data: SparklinePoint[];
  width?: number;
  height?: number;
};

const DEFAULT_W = 80;
const DEFAULT_H = 24;
const PAD = 2;

function yCap(data: SparklinePoint[]): number {
  const maxB = Math.max(...data.map((d) => d.brier), 0);
  return Math.max(0.5, maxB);
}

function brierToY(brier: number, cap: number, height: number): number {
  const clamped = Math.min(brier, cap);
  const norm = 1 - clamped / cap;
  return PAD + norm * (height - 2 * PAD);
}

export function BrierSparkline({
  data,
  width = DEFAULT_W,
  height = DEFAULT_H,
}: SparklineProps) {
  if (data.length <= 1) return null;

  const cap = yCap(data);
  const hasClip = data.some((d) => d.brier > 0.5);

  if (data.length <= 3) {
    const n = data.length;
    const slotW = (width - 2 * PAD) / n;
    const barW = Math.max(4, slotW * 0.6);
    return (
      <svg
        width={width}
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className="text-slate-400"
        aria-hidden
      >
        {data.map((d, i) => {
          const barH = Math.max(
            2,
            (1 - Math.min(d.brier, cap) / cap) * (height - 2 * PAD)
          );
          const x = PAD + i * slotW + (slotW - barW) / 2;
          const y = height - PAD - barH;
          return (
            <rect
              key={d.version}
              x={x}
              y={y}
              width={barW}
              height={barH}
              fill="currentColor"
              opacity={0.7}
            />
          );
        })}
        {hasClip && (
          <text x={width - 6} y={8} fontSize={8} fill="currentColor">
            ↑
          </text>
        )}
      </svg>
    );
  }

  const step = (width - 2 * PAD) / (data.length - 1);
  const points = data
    .map((d, i) => {
      const x = PAD + i * step;
      const y = brierToY(d.brier, cap, height);
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      className="text-slate-400"
      aria-hidden
    >
      <polyline
        points={points}
        fill="none"
        stroke="currentColor"
        strokeWidth={1.5}
        strokeLinejoin="round"
      />
      {hasClip && (
        <text x={width - 6} y={8} fontSize={8} fill="currentColor">
          ↑
        </text>
      )}
    </svg>
  );
}
