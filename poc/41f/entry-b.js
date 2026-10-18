import { createAgent } from '@agentix-e/nl2charts-core';
import { createPgConnector } from '@agentix-e/nl2charts-core/pg';
console.log(createAgent({}).ask('x'), createPgConnector({}));
