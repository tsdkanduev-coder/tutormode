type WheelLikeEvent = {
  deltaY: number;
  target: EventTarget | null;
  preventDefault: () => void;
};

function isScrollableY(node: HTMLElement): boolean {
  const style = window.getComputedStyle(node);
  return (
    (style.overflowY === "auto" || style.overflowY === "scroll") &&
    node.scrollHeight > node.clientHeight + 2
  );
}

function canConsumeScroll(node: HTMLElement, deltaY: number): boolean {
  const atBottom = node.scrollTop + node.clientHeight >= node.scrollHeight - 2;
  const atTop = node.scrollTop <= 2;
  return (deltaY > 0 && !atBottom) || (deltaY < 0 && !atTop);
}

export function findChatScrollRoot(origin: HTMLElement | null): HTMLElement | null {
  if (!origin) return null;

  let scrollRoot =
    (origin.closest("[data-chat-scroll-root='true']") as HTMLElement | null) ?? null;
  if (scrollRoot) return scrollRoot;

  let parent: HTMLElement | null = origin.parentElement;
  while (parent) {
    if (isScrollableY(parent)) {
      scrollRoot = parent;
      break;
    }
    parent = parent.parentElement;
  }

  return scrollRoot;
}

export function forwardWheelToChatScrollRoot(
  event: WheelLikeEvent,
  boundaryEl: HTMLElement | null,
): boolean {
  if (!boundaryEl || Math.abs(event.deltaY) < 1) return false;

  let node = event.target as HTMLElement | null;
  while (node && node !== boundaryEl) {
    if (isScrollableY(node) && canConsumeScroll(node, event.deltaY)) {
      return false;
    }
    node = node.parentElement;
  }

  if (isScrollableY(boundaryEl) && canConsumeScroll(boundaryEl, event.deltaY)) {
    return false;
  }

  const scrollRoot = findChatScrollRoot(boundaryEl);
  if (!scrollRoot || scrollRoot === boundaryEl) return false;

  event.preventDefault();
  scrollRoot.scrollBy({ top: event.deltaY, behavior: "auto" });
  return true;
}
