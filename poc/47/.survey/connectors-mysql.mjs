import { createConnection } from 'node:net';
export const createMysql = (cfg) => ({ kind: 'mysql', connect: () => createConnection(3306, cfg.host) });