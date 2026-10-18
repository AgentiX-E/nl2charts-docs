import { createConnection } from 'node:net';
export const createMysql = (c) => ({ kind: 'mysql', c });