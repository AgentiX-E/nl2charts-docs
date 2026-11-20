export type { Engine } from './engine/contract';
export { isEngine } from './engine/contract';
export interface AgentConfig {
    readonly engine?: unknown;
    readonly llm?: unknown;
}
export interface Agent {
    readonly ask: (q: string) => Promise<{
        sql: string;
    }>;
}
export declare function createAgent(cfg: AgentConfig): Agent;
export declare function negotiate(): 'local' | 'remote';
