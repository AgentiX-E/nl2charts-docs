import { connect } from 'node:net';
export const createPg = (cfg) => ({ kind: 'pg', connect: () => connect(5432, cfg.host) });