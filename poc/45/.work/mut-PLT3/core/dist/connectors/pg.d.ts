import { Socket } from 'node:net';
export declare function createPgConnector(cfg: { host: string }): { kind: string; connect: () => Socket };
