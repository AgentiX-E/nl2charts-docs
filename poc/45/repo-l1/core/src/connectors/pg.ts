import { connect } from 'node:net';
export function createPgConnector(cfg: { host: string }) {
  return { kind: 'pg', connect: () => connect(5432, cfg.host) };
}
