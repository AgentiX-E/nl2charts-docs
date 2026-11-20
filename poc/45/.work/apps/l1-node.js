import { createAgent } from '@agentix-e/nl2charts-core';
import { createDuckDbNode } from '@agentix-e/nl2charts-core/duckdb-node';
import { createPgConnector } from '@agentix-e/nl2charts-core/connectors/pg';
console.log(createAgent({}), createDuckDbNode({}), createPgConnector({}));
export const __ok = true;
