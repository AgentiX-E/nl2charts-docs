import pg from 'pg';
export function createPgConnector(cfg) { return { client: new pg.Client(cfg) }; }
