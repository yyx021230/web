import { useEffect, useRef, useState, type CSSProperties } from 'react';

const MIN_HEIGHT = 112;
const MAX_HEIGHT = 360;

export function useResizablePrompt() {
  const containerRef = useRef<HTMLDivElement>(null);
  const [maxHeight, setMaxHeight] = useState(MAX_HEIGHT);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    const updateBounds = () => {
      const availableHeight = containerRef.current?.clientHeight || window.innerHeight;
      // Leave room for history and the parameter toolbar, even on short screens.
      const maximum = Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, Math.floor(availableHeight * .6 - 74)));
      setMaxHeight(maximum);
    };
    updateBounds();
    const observer = typeof ResizeObserver !== 'undefined' ? new ResizeObserver(updateBounds) : null;
    if (containerRef.current) observer?.observe(containerRef.current);
    window.addEventListener('resize', updateBounds);
    return () => {
      observer?.disconnect();
      window.removeEventListener('resize', updateBounds);
    };
  }, []);

  const height = expanded ? maxHeight : MIN_HEIGHT;

  return {
    containerRef,
    expanded,
    style: { '--prompt-height': `${height}px` } as CSSProperties,
    toggleExpanded: () => setExpanded(current => !current),
  };
}
