import { connect } from 'node:net';
export const createPg = (c) => ({ kind: 'pg', c });