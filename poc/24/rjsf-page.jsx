import React from 'react';
import { createRoot } from 'react-dom/client';
import { RjsfForm } from './rjsf-form.jsx';
import { connectorSchema } from './schema.js';
const el = document.getElementById('root');
const t0 = performance.now();
createRoot(el).render(React.createElement(RjsfForm, { schema: connectorSchema, value: {}, onChange: () => {} }));
requestAnimationFrame(() => requestAnimationFrame(() => { window.__t = +(performance.now() - t0).toFixed(2); }));
