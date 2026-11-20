import { mkdirSync } from 'node:fs';
export const createFileCache = (d) => ({ kind: 'file-cache', init: () => mkdirSync(d, { recursive: true }) });