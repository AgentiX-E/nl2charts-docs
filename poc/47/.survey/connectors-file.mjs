import { readFile } from 'node:fs/promises';
export const createFile = (p) => ({ kind: 'file', read: () => readFile(p) });