export const FRAME = { width: 1080, height: 1920 } as const;
export const SAFE = { left: 64, right: 1016, bottom: 1440, stageRight: 896 } as const;
export const CAPTION = { top: 1310, height: 100, maxWidth: 900 } as const;

export type Rect = { x: number; y: number; width: number; height: number };

export function isInsideSafeArea(rect: Rect): boolean {
  return rect.x >= SAFE.left
    && rect.y >= 0
    && rect.x + rect.width <= SAFE.right
    && rect.y + rect.height <= SAFE.bottom;
}

export function isInsideStageSafeArea(rect: Rect): boolean {
  return isInsideSafeArea(rect) && rect.x + rect.width <= SAFE.stageRight;
}

export function overlaps(a: Rect, b: Rect): boolean {
  return a.x < b.x + b.width && a.x + a.width > b.x
    && a.y < b.y + b.height && a.y + a.height > b.y;
}
