import React from 'react';
import { createRoot } from 'react-dom/client';
import { renderSVG } from './chart-lib.js';

export function Chart({ spec, width, height }) {
  const ref = React.useRef(null);
  React.useEffect(() => {
    if (!ref.current) return;
    ref.current.innerHTML = renderSVG(spec, width, height);
  }, [spec, width, height]);
  return React.createElement('div', { ref, style: { width, height } });
}
export function mount(el, spec) {
  const root = createRoot(el);
  root.render(React.createElement(Chart, { spec, width: 640, height: 360 }));
  return root;
}
