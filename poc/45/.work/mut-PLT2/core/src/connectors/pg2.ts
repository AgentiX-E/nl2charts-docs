import pg from 'pg';
export const createPg2 = (cfg: { host: string }) => new pg.Client(cfg);
