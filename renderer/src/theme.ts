export const theme = {
  background: "#05070A",
  surface: "#0D1117",
  border: "#1F2933",
  text: "#F5F7FA",
  dim: "#8B95A1",
  green: "#34E39A",
  cyan: "#22D3EE",
  blue: "#60A5FA",
  purple: "#A78BFA",
  amber: "#FBBF24",
  red: "#F87171",
  grid: 8,
  radius: 20,
  safe: { side: 64, bottomReserved: 480, stageRightBuffer: 120 },
  fonts: {
    sans: "Inter, Noto Sans Devanagari, sans-serif",
    mono: "JetBrains Mono, monospace",
  },
} as const;

export const colorByName: Record<string, string> = {
  green: theme.green,
  cyan: theme.cyan,
  blue: theme.blue,
  purple: theme.purple,
  amber: theme.amber,
  red: theme.red,
  white: theme.text,
};
