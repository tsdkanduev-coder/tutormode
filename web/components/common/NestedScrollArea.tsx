"use client";

import { forwardWheelToChatScrollRoot } from "@/lib/nested-scroll";
import {
  forwardRef,
  useCallback,
  useRef,
  type HTMLAttributes,
} from "react";

type NestedScrollAreaProps = HTMLAttributes<HTMLDivElement>;

const NestedScrollArea = forwardRef<HTMLDivElement, NestedScrollAreaProps>(function NestedScrollArea(
  {
    children,
    onWheel,
    onWheelCapture,
    ...props
  },
  forwardedRef,
) {
  const ref = useRef<HTMLDivElement>(null);
  const setRef = useCallback(
    (node: HTMLDivElement | null) => {
      ref.current = node;
      if (typeof forwardedRef === "function") {
        forwardedRef(node);
      } else if (forwardedRef) {
        forwardedRef.current = node;
      }
    },
    [forwardedRef],
  );

  const handleWheel = useCallback(
    (event: React.WheelEvent<HTMLDivElement>) => {
      if (onWheel) {
        onWheel(event);
      }
      if (event.defaultPrevented) return;
      forwardWheelToChatScrollRoot(event, ref.current);
    },
    [onWheel],
  );

  const handleWheelCapture = useCallback(
    (event: React.WheelEvent<HTMLDivElement>) => {
      if (onWheelCapture) {
        onWheelCapture(event);
      }
      if (event.defaultPrevented) return;
      forwardWheelToChatScrollRoot(event, ref.current);
    },
    [onWheelCapture],
  );

  return (
    <div
      {...props}
      ref={setRef}
      onWheelCapture={handleWheelCapture}
      onWheel={handleWheel}
    >
      {children}
    </div>
  );
});

export default NestedScrollArea;
